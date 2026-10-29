import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import guardian as guardian_service
from app.agent.intents import DeterministicIntentAdapter, get_intent_adapter
from app.agent.planner import PlanNode, generate_plan, hash_plan, validate_dag, verify_plan_hash
from app.agent.tools import require_registered_tool
from app.agent.vision import EvidenceAnalysis, analyze_image, text_evidence
from app.db.models import (
    AgentConversation,
    AgentHandoff,
    AgentRun,
    AgentStep,
    Payee,
    Subscription,
)
from app.domain.schemas import (
    AgentHandoffResponse,
    AgentResumeRequest,
    AgentRunResponse,
    AgentStepResponse,
    GuardianAssessmentResponse,
    TransferDraftCreate,
)
from app.security.prompt_guard import inspect_untrusted_text
from app.services import banking as banking_service
from app.services import extended_banking as extended_service
from app.services import scheduled_tasks as scheduled_task_service
from app.services import security as security_service
from app.services.audit import append_audit_event, redact_details

TERMINAL_STATUSES = {"completed", "cancelled", "failed"}


def serializable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[union-attr]
    return value


def update_context(run: AgentRun, **values: object) -> None:
    run.context = {**run.context, **values}


def update_memory(conversation: AgentConversation, **values: object) -> None:
    conversation.memory = {**conversation.memory, **values}


async def owned_conversation(
    session: AsyncSession, user_id: str, conversation_id: str
) -> AgentConversation:
    conversation = await session.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise banking_service.domain_error(
            status.HTTP_404_NOT_FOUND,
            "AGENT_CONVERSATION_NOT_FOUND",
            "Agent 会话不存在。",
        )
    if conversation.status != "active":
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "AGENT_CONVERSATION_CLOSED",
            "Agent 会话已经关闭。",
        )
    return conversation


async def owned_run(
    session: AsyncSession, user_id: str, run_id: str, *, lock: bool = False
) -> AgentRun:
    statement = select(AgentRun).where(
        AgentRun.id == run_id, AgentRun.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    run = await session.scalar(statement)
    if run is None:
        raise banking_service.domain_error(
            status.HTTP_404_NOT_FOUND, "AGENT_RUN_NOT_FOUND", "Agent 运行不存在。"
        )
    return run


async def list_steps(session: AsyncSession, run_id: str) -> list[AgentStep]:
    rows = await session.scalars(
        select(AgentStep)
        .where(AgentStep.run_id == run_id)
        .order_by(AgentStep.sequence)
    )
    return list(rows)


async def active_handoff(
    session: AsyncSession, run_id: str
) -> AgentHandoff | None:
    return await session.scalar(
        select(AgentHandoff)
        .where(AgentHandoff.run_id == run_id, AgentHandoff.status == "requested")
        .order_by(AgentHandoff.requested_at.desc())
        .limit(1)
    )


async def latest_handoff(
    session: AsyncSession, run_id: str
) -> AgentHandoff | None:
    return await session.scalar(
        select(AgentHandoff)
        .where(AgentHandoff.run_id == run_id)
        .order_by(AgentHandoff.requested_at.desc())
        .limit(1)
    )


async def present_run(session: AsyncSession, run: AgentRun) -> AgentRunResponse:
    steps = await list_steps(session, run.id)
    handoff = await latest_handoff(session, run.id)
    guardian = await guardian_service.assessment_for_run(session, run.id)
    response = AgentRunResponse.model_validate(run)
    return response.model_copy(
        update={
            "steps": [AgentStepResponse.model_validate(step) for step in steps],
            "handoff": AgentHandoffResponse.model_validate(handoff) if handoff else None,
            "guardian": GuardianAssessmentResponse.model_validate(guardian) if guardian else None,
        }
    )


GUARDIAN_REVIEW_INTENTS = {
    "transfer.create", "transfer.schedule", "collection.aa",
    "subscription.cancel", "subscription.reminder", "card.manage", "card.apply",
    "card.limit", "card.restriction", "investment.subscribe", "investment.redeem",
    "occasion.plan", "fraud.assess",
}


def highest_plan_risk(plan: list[dict[str, object]]) -> str:
    rank = {"green": 1, "yellow": 2, "red": 3}
    return max((str(node.get("risk_level", "green")) for node in plan), key=lambda value: rank.get(value, 1), default="green")


def guardian_plan(
    plan: list[dict[str, object]], intent: str, disposition: str
) -> list[dict[str, object]]:
    """Insert a policy-owned review node and re-route unsafe DAGs before execution."""
    if disposition == "block":
        enhanced = [
            PlanNode(id="guardian_review", kind="tool", tool_name="guardian.risk.assess", depends_on=[], risk_level="green", description="Guardian Agent 独立审查意图、证据与银行家提案"),
            PlanNode(id="fraud_policy_block", kind="gate", tool_name=None, depends_on=["guardian_review"], risk_level="red", description="命中高风险反诈策略，阻断业务副作用"),
            PlanNode(id="human_handoff", kind="gate", tool_name=None, depends_on=["fraud_policy_block"], risk_level="red", description="保留证据并转交人工反诈复核"),
        ]
    elif intent in GUARDIAN_REVIEW_INTENTS:
        review = PlanNode(id="guardian_review", kind="tool", tool_name="guardian.risk.assess", depends_on=[], risk_level="green", description="Guardian Agent 在业务执行前独立复核风险")
        enhanced = [review]
        for raw in plan:
            if raw.get("id") == "guardian_review":
                continue
            node = dict(raw)
            dependencies = list(node.get("depends_on", []))
            if not dependencies:
                dependencies = ["guardian_review"]
            if disposition == "step_up" and node.get("id") == "authorization_gate":
                node["risk_level"] = "red"
                node["description"] = f"{node.get('description', '')}；Guardian 动态提级为强验证"
            node["depends_on"] = dependencies
            enhanced.append(PlanNode.model_validate(node))
    else:
        enhanced = [PlanNode.model_validate(node) for node in plan]
    validate_dag(enhanced)
    return [node.model_dump(mode="json") for node in enhanced]


def node_sequence(run: AgentRun, node_id: str) -> int:
    for index, node in enumerate(run.plan, 1):
        if node["id"] == node_id:
            return index
    raise ValueError(f"Unknown plan node: {node_id}")


async def begin_step(
    session: AsyncSession,
    run: AgentRun,
    node_id: str,
    *,
    input_data: dict[str, object] | None = None,
) -> AgentStep:
    existing = await session.scalar(
        select(AgentStep).where(
            AgentStep.run_id == run.id, AgentStep.node_id == node_id
        )
    )
    if existing is not None:
        if existing.status == "paused":
            existing.status = "running"
        return existing
    node = next(item for item in run.plan if item["id"] == node_id)
    tool_name = node.get("tool_name")
    if tool_name:
        require_registered_tool(str(tool_name))
    step = AgentStep(
        id=str(uuid4()),
        run_id=run.id,
        node_id=node_id,
        sequence=node_sequence(run, node_id),
        kind=str(node["kind"]),
        tool_name=str(tool_name) if tool_name else None,
        status="running",
        input_data=redact_details(input_data or {}),
        output_data={},
        started_at=datetime.now(UTC),
    )
    run.current_node_id = node_id
    session.add(step)
    await session.flush()
    return step


async def complete_step(
    session: AsyncSession, step: AgentStep, output_data: dict[str, object]
) -> None:
    step.status = "completed"
    step.output_data = serializable(output_data)  # type: ignore[assignment]
    step.finished_at = datetime.now(UTC)
    await session.flush()


async def pause_step(
    session: AsyncSession,
    run: AgentRun,
    node_id: str,
    run_status: str,
    pending_action: dict[str, object],
) -> AgentRun:
    step = await begin_step(session, run, node_id)
    step.status = "paused"
    step.output_data = {"pending_action": serializable(pending_action)}
    run.status = run_status
    run.pending_action = serializable(pending_action)  # type: ignore[assignment]
    run.response_text = str(pending_action.get("prompt", "需要用户继续操作。"))
    run.version += 1
    await append_audit_event(
        session,
        user_id=run.user_id,
        action="agent.run.pause",
        outcome="recorded",
        resource_type="agent_run",
        resource_id=run.id,
        reason_codes=[run_status.upper()],
        details={"node_id": node_id, "pending_action": pending_action},
    )
    await guardian_service.persist_receipt(session, run)
    await session.commit()
    return run


async def mark_completed(
    session: AsyncSession,
    run: AgentRun,
    result: dict[str, object],
    response_text: str,
) -> AgentRun:
    run.status = "completed"
    run.pending_action = None
    run.result = serializable(result)  # type: ignore[assignment]
    run.response_text = response_text
    run.current_node_id = None
    run.version += 1
    await append_audit_event(
        session,
        user_id=run.user_id,
        action="agent.run.complete",
        outcome="allowed",
        resource_type="agent_run",
        resource_id=run.id,
        reason_codes=["PLAN_COMPLETED"],
        details={"intent": run.intent},
    )
    await guardian_service.persist_receipt(session, run)
    await session.commit()
    return run


async def create_handoff(
    session: AsyncSession,
    run: AgentRun,
    reason: str,
    *,
    automatic: bool,
) -> AgentHandoff:
    if run.status in TERMINAL_STATUSES:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "AGENT_RUN_TERMINAL",
            "已结束的运行不能转交人工。",
        )
    existing = await active_handoff(session, run.id)
    if existing is not None:
        return existing
    resume_status = run.status
    handoff = AgentHandoff(
        id=str(uuid4()),
        run_id=run.id,
        user_id=run.user_id,
        status="requested",
        reason=reason,
        resume_status=resume_status,
        requested_at=datetime.now(UTC),
    )
    run.status = "human_review"
    run.pending_action = {
        "type": "human_review",
        "prompt": "该任务已暂停并转交人工处理。",
        "reason": reason,
    }
    run.response_text = "该任务已暂停并转交人工处理。"
    run.version += 1
    session.add(handoff)
    await append_audit_event(
        session,
        user_id=run.user_id,
        action="agent.handoff.request",
        outcome="recorded",
        resource_type="agent_run",
        resource_id=run.id,
        reason_codes=["AUTOMATIC_HANDOFF" if automatic else "USER_REQUESTED_HANDOFF"],
        details={"reason": reason, "resume_status": resume_status},
    )
    await guardian_service.persist_receipt(session, run)
    await session.commit()
    return handoff


async def run_green_query(
    session: AsyncSession, run: AgentRun, conversation: AgentConversation
) -> AgentRun:
    if run.intent == "account.balance":
        step = await begin_step(session, run, "query_accounts")
        accounts = await banking_service.list_user_accounts(session, run.user_id)
        items = [
            {
                "id": account.id,
                "name": account.name,
                "masked_number": account.masked_number,
                "balance": str(account.balance),
                "currency": account.currency,
            }
            for account in accounts
        ]
        total = sum((account.balance for account in accounts), Decimal(0))
        await complete_step(session, step, {"items": items, "total_balance": str(total)})
        return await mark_completed(
            session,
            run,
            {"accounts": items, "total_balance": str(total), "currency": "CNY"},
            f"你的账户总资产为 {total:.2f} 元。",
        )

    if run.intent == "bill.summary":
        month = str(run.context["slots"]["month"])
        step = await begin_step(session, run, "summarize_bill", input_data={"month": month})
        summary = await banking_service.summarize_month(session, run.user_id, month)
        output = summary.model_dump(mode="json")
        await complete_step(session, step, output)
        update_memory(conversation, last_bill_month=month, last_intent=run.intent)
        return await mark_completed(
            session,
            run,
            output,
            f"{month} 支出 {summary.outflow:.2f} 元，收入 {summary.income:.2f} 元。",
        )

    if run.intent == "bill.annual":
        year = int(str(run.context["slots"]["year"]))
        step = await begin_step(session, run, "annual_report", input_data={"year": year})
        output = await extended_service.summarize_year(session, run.user_id, year)
        await complete_step(session, step, output)
        return await mark_completed(session, run, output, f"{year} 年支出 {output['outflow']} 元，年度收支报告已生成。")

    if run.intent == "investment.holdings":
        step = await begin_step(session, run, "list_holdings")
        items = await extended_service.list_holdings(session, run.user_id)
        await complete_step(session, step, {"holdings": items})
        return await mark_completed(session, run, {"holdings": items}, f"当前共有 {len(items)} 笔有效理财持仓。")

    if run.intent == "occasion.detect":
        step = await begin_step(session, run, "scan_life_events")
        items = await extended_service.scan_life_events(session, run.user_id)
        await complete_step(session, step, {"life_events": items})
        prompt = f"检测到 {len(items)} 个已授权生活事件，可以继续让我为它生成跨场景计划。"
        return await mark_completed(session, run, {"life_events": items}, prompt)

    if run.intent == "card.list":
        step = await begin_step(session, run, "list_cards")
        cards = await banking_service.list_user_cards(session, run.user_id)
        items = [
            {
                "id": card.id,
                "card_name": card.card_name,
                "network": card.network,
                "masked_number": card.masked_number,
                "last4": card.last4,
                "status": card.status,
                "daily_limit": str(card.daily_limit),
                "transaction_limit": str(card.transaction_limit),
                "online_transactions_enabled": card.online_transactions_enabled,
            }
            for card in cards
        ]
        await complete_step(session, step, {"items": items})
        return await mark_completed(
            session,
            run,
            {"cards": items},
            f"你共有 {len(items)} 张银行卡，我已隐藏完整卡号。",
        )

    if run.intent != "subscription.list":
        raise ValueError(f"Unsupported green intent: {run.intent}")
    step = await begin_step(session, run, "list_subscriptions")
    subscriptions = await banking_service.list_user_subscriptions(
        session, run.user_id, "active"
    )
    monthly = sum((item.amount for item in subscriptions), Decimal(0))
    items = [
        {
            "merchant": item.merchant,
            "product_name": item.product_name,
            "amount": str(item.amount),
            "currency": item.currency,
            "next_charge_at": serializable(item.next_charge_at),
        }
        for item in subscriptions
    ]
    await complete_step(session, step, {"items": items, "monthly_equivalent": str(monthly)})
    return await mark_completed(
        session,
        run,
        {"subscriptions": items, "monthly_equivalent": str(monthly)},
        f"识别到 {len(items)} 个活跃订阅，每月合计 {monthly:.2f} 元。",
    )


async def resolve_account_step(session: AsyncSession, run: AgentRun) -> None:
    if run.context.get("source_account_id"):
        return
    step = await begin_step(session, run, "resolve_account")
    accounts = await banking_service.list_user_accounts(session, run.user_id)
    hint = str(run.context.get("slots", {}).get("source_account_hint") or "")
    candidates = [account for account in accounts if account.status == "active"]
    selected = next((account for account in candidates if hint and hint in account.name), None)
    selected = selected or next(
        (account for account in candidates if account.account_type == "checking"), None
    )
    if selected is None:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "NO_ACTIVE_SOURCE_ACCOUNT",
            "没有可用于转账的活跃账户。",
        )
    update_context(run, source_account_id=selected.id, source_account_name=selected.name)
    await complete_step(
        session,
        step,
        {"account_id": selected.id, "name": selected.name, "status": selected.status},
    )
    await session.commit()


async def resolve_payee_step(
    session: AsyncSession, run: AgentRun, conversation: AgentConversation
) -> AgentRun | None:
    if run.context.get("payee_id"):
        return None
    slots = run.context.get("slots", {})
    remembered_id = slots.get("recipient_id") if isinstance(slots, dict) else None
    step = await begin_step(session, run, "resolve_payee")
    if remembered_id:
        payee = await session.scalar(
            select(Payee).where(
                Payee.id == str(remembered_id), Payee.owner_user_id == run.user_id
            )
        )
        rows = [payee] if payee else []
    else:
        query = str(slots.get("recipient_query") or "") if isinstance(slots, dict) else ""
        rows = await banking_service.search_user_payees(session, run.user_id, query, 10)
    if not rows:
        return await pause_step(
            session,
            run,
            "resolve_payee",
            "waiting_clarification",
            {
                "type": "missing_payee",
                "prompt": "没有找到收款人，请补充姓名或选择已有联系人。",
            },
        )
    if len(rows) > 1:
        options = [
            {
                "id": item.id,
                "name": item.name,
                "bank_name": item.bank_name,
                "account_masked": item.account_masked,
                "alias": item.alias,
            }
            for item in rows
        ]
        return await pause_step(
            session,
            run,
            "resolve_payee",
            "waiting_clarification",
            {
                "type": "payee_disambiguation",
                "prompt": "找到多个同名收款人，请选择后继续。",
                "options": options,
            },
        )
    payee = rows[0]
    update_context(run, payee_id=payee.id, payee_name=payee.name)
    update_memory(
        conversation,
        last_payee_id=payee.id,
        last_payee_name=payee.name,
        last_intent=run.intent,
    )
    await complete_step(
        session,
        step,
        {"payee_id": payee.id, "name": payee.name, "account_masked": payee.account_masked},
    )
    await session.commit()
    return None


async def execute_authorized_transfer(
    session: AsyncSession, run: AgentRun
) -> AgentRun:
    draft_id = str(run.context["draft_id"])
    step = await begin_step(
        session,
        run,
        "execute_transfer",
        input_data={"draft_id": draft_id, "idempotency_key": f"agent-run-{run.id}"},
    )
    execution = await security_service.execute_transfer(
        session, run.user_id, draft_id, f"agent-run-{run.id}"
    )
    output = {
        "execution_id": execution.id,
        "receipt_no": execution.receipt_no,
        "amount": str(execution.amount),
        "currency": execution.currency,
        "status": execution.status,
    }
    await complete_step(session, step, output)
    return await mark_completed(
        session,
        run,
        output,
        f"转账已完成，金额 {execution.amount:.2f} 元，回执号 {execution.receipt_no}。",
    )


async def drive_transfer(
    session: AsyncSession, run: AgentRun, conversation: AgentConversation
) -> AgentRun:
    slots = run.context.get("slots", {})
    missing = [
        field
        for field in ("amount", "recipient_query")
        if not isinstance(slots, dict) or not slots.get(field)
    ]
    if isinstance(slots, dict) and slots.get("recipient_id"):
        missing = [field for field in missing if field != "recipient_query"]
    if missing:
        return await pause_step(
            session,
            run,
            "resolve_payee" if "recipient_query" in missing else "resolve_account",
            "waiting_clarification",
            {
                "type": "missing_slots",
                "prompt": f"请补充：{'、'.join(missing)}。",
                "fields": missing,
            },
        )

    await resolve_account_step(session, run)
    paused = await resolve_payee_step(session, run, conversation)
    if paused is not None:
        return paused

    if not run.context.get("draft_id"):
        await security_service.assert_not_locked(session, run.user_id)
        step = await begin_step(
            session,
            run,
            "create_draft",
            input_data={
                "source_account_id": run.context["source_account_id"],
                "payee_id": run.context["payee_id"],
                "amount": slots["amount"],
            },
        )
        draft = await banking_service.create_transfer_draft(
            session,
            run.user_id,
            TransferDraftCreate(
                source_account_id=str(run.context["source_account_id"]),
                payee_id=str(run.context["payee_id"]),
                amount=Decimal(str(slots["amount"])),
                currency="CNY",
                memo=str(slots["memo"]) if slots.get("memo") else None,
            ),
        )
        update_context(run, draft_id=draft.id)
        await complete_step(
            session, step, {"draft_id": draft.id, "status": draft.status}
        )
        await session.commit()

    if not run.context.get("risk_level"):
        step = await begin_step(
            session,
            run,
            "evaluate_policy",
            input_data={"draft_id": run.context["draft_id"]},
        )
        draft, decision = await security_service.evaluate_transfer_policy(
            session, run.user_id, str(run.context["draft_id"])
        )
        if (
            str(run.context.get("guardian", {}).get("disposition")) == "step_up"
            and decision.risk_level == "yellow"
        ):
            decision.risk_level = "red"
            decision.required_action = "strong_auth"
            decision.reason_codes = [*decision.reason_codes, "GUARDIAN_DYNAMIC_STEP_UP"]
            draft.status = "awaiting_auth"
            await append_audit_event(
                session,
                user_id=run.user_id,
                action="guardian.policy.reroute",
                outcome="recorded",
                risk_level="red",
                resource_type="transfer_draft",
                resource_id=draft.id,
                correlation_id=run.id,
                reason_codes=["GUARDIAN_DYNAMIC_STEP_UP"],
                details={"from": "yellow_confirmation", "to": "strong_auth"},
            )
        update_context(
            run,
            risk_level=decision.risk_level,
            draft_status=draft.status,
            policy_decision_id=decision.id,
        )
        await complete_step(
            session,
            step,
            {
                "risk_level": decision.risk_level,
                "required_action": decision.required_action,
                "reason_codes": decision.reason_codes,
                "projected_daily_total": str(decision.projected_daily_total),
            },
        )
        await session.commit()

    summary = {
        "amount": str(slots["amount"]),
        "currency": "CNY",
        "source_account": run.context["source_account_name"],
        "payee": run.context["payee_name"],
        "draft_id": run.context["draft_id"],
    }
    if run.context["risk_level"] == "yellow":
        return await pause_step(
            session,
            run,
            "authorization_gate",
            "waiting_confirmation",
            {
                "type": "transfer_confirmation",
                "prompt": "这是黄色操作，请核对详情并明确确认。",
                "details": summary,
            },
        )

    if not run.context.get("challenge_id"):
        challenge = await security_service.create_auth_challenge(
            session, run.user_id, str(run.context["draft_id"])
        )
        update_context(run, challenge_id=challenge.id)
        await session.commit()
    return await pause_step(
        session,
        run,
        "authorization_gate",
        "waiting_auth",
        {
            "type": "strong_authentication",
            "prompt": "这是红色操作，请输入短信验证码完成强验证。",
            "details": summary,
            "challenge_id": run.context["challenge_id"],
        },
    )


async def resolve_subscription_step(
    session: AsyncSession, run: AgentRun
) -> AgentRun | None:
    if run.context.get("subscription_id"):
        return None
    slots = run.context.get("slots", {})
    selected_id = slots.get("subscription_id") if isinstance(slots, dict) else None
    step = await begin_step(session, run, "resolve_subscription")
    if selected_id:
        subscription = await session.scalar(
            select(Subscription).where(
                Subscription.id == str(selected_id),
                Subscription.user_id == run.user_id,
                Subscription.status == "active",
            )
        )
        rows = [subscription] if subscription else []
    else:
        query = str(slots.get("subscription_query") or "") if isinstance(slots, dict) else ""
        rows = await banking_service.search_user_subscriptions(session, run.user_id, query)
    if not rows:
        return await pause_step(
            session,
            run,
            "resolve_subscription",
            "waiting_clarification",
            {
                "type": "missing_slots",
                "prompt": "请告诉我需要取消哪个平台或会员，例如“星幕视频”。",
                "fields": ["subscription_query"],
            },
        )
    if len(rows) > 1:
        options = [
            {
                "id": item.id,
                "merchant": item.merchant,
                "product_name": item.product_name,
                "amount": str(item.amount),
                "next_charge_at": serializable(item.next_charge_at),
            }
            for item in rows
        ]
        return await pause_step(
            session,
            run,
            "resolve_subscription",
            "waiting_clarification",
            {
                "type": "subscription_disambiguation",
                "prompt": "找到多个匹配订阅，请选择需要取消的一项。",
                "options": options,
            },
        )
    subscription = rows[0]
    update_context(
        run,
        subscription_id=subscription.id,
        subscription_merchant=subscription.merchant,
        subscription_product=subscription.product_name,
        subscription_amount=str(subscription.amount),
    )
    await complete_step(
        session,
        step,
        {
            "subscription_id": subscription.id,
            "merchant": subscription.merchant,
            "product_name": subscription.product_name,
        },
    )
    await session.commit()
    return None


async def execute_subscription_cancellation(
    session: AsyncSession, run: AgentRun
) -> AgentRun:
    step = await begin_step(
        session,
        run,
        "cancel_subscription",
        input_data={"subscription_id": run.context["subscription_id"]},
    )
    subscription = await banking_service.cancel_subscription(
        session, run.user_id, str(run.context["subscription_id"])
    )
    output = {
        "subscription_id": subscription.id,
        "merchant": subscription.merchant,
        "product_name": subscription.product_name,
        "amount": str(subscription.amount),
        "status": subscription.status,
    }
    await complete_step(session, step, output)
    return await mark_completed(
        session,
        run,
        output,
        f"已取消 {subscription.merchant} 的{subscription.product_name}，后续不会自动续费。",
    )


async def drive_subscription_cancel(session: AsyncSession, run: AgentRun) -> AgentRun:
    slots = run.context.get("slots", {})
    if not isinstance(slots, dict) or not (
        slots.get("subscription_query") or slots.get("subscription_id")
    ):
        return await pause_step(
            session,
            run,
            "resolve_subscription",
            "waiting_clarification",
            {
                "type": "missing_slots",
                "prompt": "请告诉我需要取消哪个平台或会员，例如“星幕视频”。",
                "fields": ["subscription_query"],
            },
        )
    paused = await resolve_subscription_step(session, run)
    if paused is not None:
        return paused
    return await pause_step(
        session,
        run,
        "authorization_gate",
        "waiting_confirmation",
        {
            "type": "subscription_confirmation",
            "prompt": "取消后将停止后续自动续费，请确认操作。",
            "details": {
                "merchant": run.context["subscription_merchant"],
                "product_name": run.context["subscription_product"],
                "amount": run.context["subscription_amount"],
                "subscription_id": run.context["subscription_id"],
            },
        },
    )


async def execute_card_action(session: AsyncSession, run: AgentRun) -> AgentRun:
    slots = run.context.get("slots", {})
    action = str(slots.get("card_action")) if isinstance(slots, dict) else ""
    step = await begin_step(
        session,
        run,
        "update_card_status",
        input_data={"card_id": run.context["card_id"], "action": action},
    )
    card = await banking_service.change_card_status(
        session, run.user_id, str(run.context["card_id"]), action
    )
    output = {
        "card_id": card.id,
        "card_name": card.card_name,
        "last4": card.last4,
        "masked_number": card.masked_number,
        "status": card.status,
        "action": action,
    }
    await complete_step(session, step, output)
    action_text = {"lock": "冻结", "unlock": "解锁", "report_lost": "挂失"}[action]
    return await mark_completed(
        session,
        run,
        output,
        f"尾号 {card.last4} 的银行卡已完成{action_text}。",
    )


async def drive_card_manage(session: AsyncSession, run: AgentRun) -> AgentRun:
    slots = run.context.get("slots", {})
    if not isinstance(slots, dict) or not slots.get("card_action"):
        return await pause_step(
            session,
            run,
            "resolve_card",
            "waiting_clarification",
            {
                "type": "missing_slots",
                "prompt": "请说明要冻结、解锁还是挂失银行卡。",
                "fields": ["card_action"],
            },
        )
    if not run.context.get("card_id"):
        card = await banking_service.resolve_user_card(
            session,
            run.user_id,
            last4=str(slots.get("card_last4") or "") or None,
            card_id=str(slots.get("card_id") or "") or None,
        )
        if card is None:
            return await pause_step(
                session,
                run,
                "resolve_card",
                "waiting_clarification",
                {
                    "type": "missing_slots",
                    "prompt": "请补充银行卡尾号，例如“尾号 6688”。",
                    "fields": ["card_last4"],
                },
            )
        step = await begin_step(session, run, "resolve_card")
        update_context(
            run,
            card_id=card.id,
            card_name=card.card_name,
            card_last4=card.last4,
            card_masked=card.masked_number,
            card_status=card.status,
        )
        await complete_step(
            session,
            step,
            {"card_id": card.id, "last4": card.last4, "status": card.status},
        )
        await session.commit()
    if not run.context.get("challenge_id"):
        challenge = await security_service.create_operation_auth_challenge(
            session,
            run.user_id,
            "bank_card",
            str(run.context["card_id"]),
            str(slots["card_action"]),
        )
        update_context(run, challenge_id=challenge.id)
        await session.commit()
    action_text = {"lock": "冻结", "unlock": "解锁", "report_lost": "挂失"}.get(
        str(slots["card_action"]), "变更状态"
    )
    return await pause_step(
        session,
        run,
        "authorization_gate",
        "waiting_auth",
        {
            "type": "strong_authentication",
            "prompt": f"银行卡{action_text}属于红色操作，请完成短信强验证。",
            "details": {
                "operation": "card_manage",
                "action": slots["card_action"],
                "card_name": run.context["card_name"],
                "card": run.context["card_masked"],
                "status": run.context["card_status"],
            },
            "challenge_id": run.context["challenge_id"],
        },
    )


async def drive_investment_recommendation(
    session: AsyncSession, run: AgentRun
) -> AgentRun:
    slots = run.context.get("slots", {})
    profile_step = await begin_step(session, run, "load_risk_profile")
    user = await banking_service.get_user(session, run.user_id)
    await complete_step(session, profile_step, {"risk_profile": user.risk_profile})
    await session.commit()

    required = ("investment_amount", "horizon_months")
    missing = [
        field for field in required if not isinstance(slots, dict) or not slots.get(field)
    ]
    if missing:
        return await pause_step(
            session,
            run,
            "collect_preferences",
            "waiting_clarification",
            {
                "type": "missing_slots",
                "prompt": "为了匹配合适产品，请补充投资金额和预计持有期限。",
                "fields": missing,
            },
        )

    preferences_step = await begin_step(session, run, "collect_preferences")
    await complete_step(
        session,
        preferences_step,
        {
            "investment_amount": slots["investment_amount"],
            "horizon_months": slots["horizon_months"],
            "risk_preference": slots.get("risk_preference"),
        },
    )
    recommendation_step = await begin_step(
        session,
        run,
        "recommend_products",
        input_data={
            "amount": slots["investment_amount"],
            "horizon_months": slots["horizon_months"],
        },
    )
    products, effective_profile = await banking_service.recommend_investments(
        session,
        run.user_id,
        Decimal(str(slots["investment_amount"])),
        int(str(slots["horizon_months"])),
        str(slots.get("risk_preference")) if slots.get("risk_preference") else None,
    )
    items = [
        {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "risk_level": product.risk_level,
            "min_amount": str(product.min_amount),
            "expected_return_low": str(product.expected_return_low),
            "expected_return_high": str(product.expected_return_high),
            "term_months": product.term_months,
            "liquidity": product.liquidity,
            "description": product.description,
        }
        for product in products
    ]
    output = {
        "products": items,
        "investment_amount": str(slots["investment_amount"]),
        "horizon_months": str(slots["horizon_months"]),
        "user_risk_profile": user.risk_profile,
        "effective_risk_profile": effective_profile,
        "advisory_only": True,
    }
    await complete_step(session, recommendation_step, output)
    return await mark_completed(
        session,
        run,
        output,
        f"依据你的{user.risk_profile}风险评估，我筛选出 {len(items)} 个匹配产品。推荐仅供参考，不会自动申购。",
    )


def occasion_catalog(budget: Decimal) -> list[dict[str, object]]:
    flower = (budget * Decimal("0.42")).quantize(Decimal("0.01"))
    cake = (budget * Decimal("0.36")).quantize(Decimal("0.01"))
    delivery = (budget * Decimal("0.04")).quantize(Decimal("0.01"))
    contingency = budget - flower - cake - delivery
    return [
        {
            "category": "鲜花",
            "merchant": "花间集·认证商户",
            "item": "当季主题花束",
            "estimated_amount": str(flower),
        },
        {
            "category": "蛋糕",
            "merchant": "云朵烘焙·认证商户",
            "item": "生日主题蛋糕",
            "estimated_amount": str(cake),
        },
        {
            "category": "配送",
            "merchant": "青穗同城配送",
            "item": "定时配送",
            "estimated_amount": str(delivery),
        },
        {
            "category": "预留",
            "merchant": "青穗预算保护",
            "item": "价格波动备用金",
            "estimated_amount": str(contingency),
        },
    ]


async def drive_occasion_plan(session: AsyncSession, run: AgentRun) -> AgentRun:
    slots = run.context.get("slots", {})
    required = ("person", "event_date", "budget")
    missing = [
        field for field in required if not isinstance(slots, dict) or not slots.get(field)
    ]
    if missing:
        return await pause_step(
            session,
            run,
            "collect_occasion_details",
            "waiting_clarification",
            {
                "type": "missing_slots",
                "prompt": "请补充生日对象、具体日期和总预算。",
                "fields": missing,
            },
        )

    collect_step = await begin_step(session, run, "collect_occasion_details")
    await complete_step(session, collect_step, {key: slots[key] for key in required})
    budget = Decimal(str(slots["budget"]))
    if budget <= 0:
        raise banking_service.domain_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "INVALID_OCCASION_BUDGET", "预算必须大于 0。"
        )

    accounts = await banking_service.list_user_accounts(session, run.user_id)
    account = next((item for item in accounts if item.status == "active"), None)
    if account is None:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT, "NO_ACTIVE_ACCOUNT", "没有可用于资金预留的账户。"
        )
    reserved = await scheduled_task_service.active_reserved_total(session, run.user_id, account.id)
    available = account.balance - reserved
    if budget > available:
        await append_audit_event(
            session,
            user_id=run.user_id,
            action="occasion.budget.check",
            outcome="denied",
            risk_level="yellow",
            resource_type="agent_run",
            resource_id=run.id,
            reason_codes=["INSUFFICIENT_AVAILABLE_BUDGET"],
            details={"requested": str(budget), "available": str(available)},
        )
        run.status = "failed"
        run.error_code = "INSUFFICIENT_AVAILABLE_BUDGET"
        run.response_text = f"扣除其他任务预留后，可用余额为 {available:.2f} 元，无法预留本次预算。"
        await session.commit()
        return run
    budget_step = await begin_step(session, run, "check_budget")
    await complete_step(
        session,
        budget_step,
        {
            "account_id": account.id,
            "balance": str(account.balance),
            "already_reserved": str(reserved),
            "available": str(available),
            "requested": str(budget),
        },
    )

    items = occasion_catalog(budget)
    catalog_step = await begin_step(session, run, "select_occasion_items")
    await complete_step(session, catalog_step, {"items": items, "catalog": "trusted_demo_v1"})
    event_date = datetime.fromisoformat(str(slots["event_date"])).replace(
        hour=2, minute=0, tzinfo=UTC
    )
    execute_at = event_date - timedelta(days=int(str(slots.get("lead_days") or "2")))
    update_context(
        run,
        occasion_account_id=account.id,
        occasion_items=items,
        occasion_execute_at=execute_at.isoformat(),
    )
    await session.commit()
    return await pause_step(
        session,
        run,
        "authorization_gate",
        "waiting_confirmation",
        {
            "type": "occasion_confirmation",
            "prompt": "跨场景计划已生成。确认后将预留预算并创建定时任务，不会立即付款。",
            "details": {
                "person": slots["person"],
                "occasion": slots["occasion"],
                "event_date": slots["event_date"],
                "execute_at": execute_at.isoformat(),
                "budget": str(budget),
                "source_account": account.name,
                "items": items,
            },
        },
    )


async def execute_occasion_plan(session: AsyncSession, run: AgentRun) -> AgentRun:
    slots = run.context["slots"]
    account = await banking_service.get_owned_account(
        session, run.user_id, str(run.context["occasion_account_id"])
    )
    task_step = await begin_step(session, run, "create_scheduled_task")
    task = await scheduled_task_service.create_occasion_task(
        session,
        user_id=run.user_id,
        run_id=run.id,
        account=account,
        person=str(slots["person"]),
        occasion=str(slots["occasion"]),
        execute_at=datetime.fromisoformat(str(run.context["occasion_execute_at"])),
        budget=Decimal(str(slots["budget"])),
        items=list(run.context["occasion_items"]),
        plan=run.plan,
    )
    output = {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "execute_at": task.execute_at.isoformat(),
        "budget": str(task.budget),
        "reserved_amount": str(task.reserved_amount),
        "items": task.items,
    }
    await complete_step(session, task_step, output)
    return await mark_completed(
        session,
        run,
        output,
        f"已为{slots['person']}创建{slots['occasion']}准备任务，预留 {task.budget:.2f} 元，将在活动前执行。",
    )


EXTENDED_WRITE_INTENTS = {
    "transfer.schedule",
    "collection.aa",
    "subscription.reminder",
    "card.apply",
    "card.limit",
    "card.restriction",
    "investment.subscribe",
    "investment.redeem",
}
YELLOW_WRITE_INTENTS = {"collection.aa", "subscription.reminder"}


async def execute_extended_operation(session: AsyncSession, run: AgentRun) -> AgentRun:
    slots = dict(run.context.get("slots", {}))
    step = await begin_step(session, run, "execute_operation", input_data=slots)
    result = await extended_service.execute_operation(
        session, run.user_id, run.id, run.intent, slots
    )
    await complete_step(session, step, result)
    labels = {
        "transfer.schedule": "定时转账已创建",
        "collection.aa": "AA 收款已发起",
        "subscription.reminder": "续费提醒已创建",
        "card.apply": "卡片申请已完成",
        "card.limit": "卡片单笔限额已更新",
        "card.restriction": "线上交易权限已更新",
        "investment.subscribe": "理财申购已完成",
        "investment.redeem": "理财赎回已完成",
    }
    return await mark_completed(session, run, result, f"{labels[run.intent]}，操作编号 {result['operation_id'][:8]}。")


async def drive_extended_operation(session: AsyncSession, run: AgentRun) -> AgentRun:
    missing = list(run.context.get("missing_slots", []))
    if missing:
        return await pause_step(
            session, run, "prepare_operation", "waiting_clarification",
            {"type": "missing_slots", "fields": missing, "prompt": f"请补充：{'、'.join(missing)}。"},
        )
    prepare = await begin_step(session, run, "prepare_operation", input_data=dict(run.context.get("slots", {})))
    await complete_step(session, prepare, {"validated": True, "executor": "whitelist"})
    guardian_disposition = str(run.context.get("guardian", {}).get("disposition", "allow"))
    if run.intent in YELLOW_WRITE_INTENTS and guardian_disposition != "step_up":
        return await pause_step(
            session, run, "authorization_gate", "waiting_confirmation",
            {"type": "operation_confirmation", "operation": run.intent, "details": run.context.get("slots", {}), "prompt": "请核对操作详情并明确确认。"},
        )
    challenge = await security_service.create_operation_auth_challenge(
        session, run.user_id, "agent_run", run.id, run.intent
    )
    update_context(run, challenge_id=challenge.id)
    return await pause_step(
        session, run, "authorization_gate", "waiting_auth",
        {"type": "strong_authentication", "operation": run.intent, "details": {"operation": run.intent, **dict(run.context.get("slots", {}))}, "challenge_id": challenge.id, "destination": challenge.destination_masked, "prompt": "该操作需要强验证，请输入六位短信验证码。"},
    )


async def complete_guardian_review(session: AsyncSession, run: AgentRun) -> None:
    if not any(node.get("id") == "guardian_review" for node in run.plan):
        return
    existing = await session.scalar(
        select(AgentStep).where(
            AgentStep.run_id == run.id,
            AgentStep.node_id == "guardian_review",
            AgentStep.status == "completed",
        )
    )
    if existing:
        return
    assessment = await guardian_service.assessment_for_run(session, run.id)
    if assessment is None:
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "GUARDIAN_ASSESSMENT_MISSING",
            "Guardian 风险评估缺失，已停止执行。",
        )
    step = await begin_step(
        session,
        run,
        "guardian_review",
        input_data={"banker_proposal": assessment.banker_proposal},
    )
    await complete_step(
        session,
        step,
        {
            "scam_score": assessment.scam_score,
            "disposition": assessment.disposition,
            "signals": assessment.signals,
            "original_risk": assessment.original_risk,
            "effective_risk": assessment.effective_risk,
            "evidence_fingerprint": assessment.evidence_fingerprint,
        },
    )
    await session.commit()


async def drive_guardian_block(session: AsyncSession, run: AgentRun) -> AgentRun:
    gate = await begin_step(session, run, "fraud_policy_block")
    await complete_step(
        session,
        gate,
        {"blocked": True, "reason": "Guardian 风险分达到阻断阈值，未调用任何业务写工具。"},
    )
    handoff_step = await begin_step(session, run, "human_handoff")
    handoff_step.status = "paused"
    handoff_step.output_data = {"reason": "suspected_fraud", "side_effects_prevented": True}
    await create_handoff(
        session,
        run,
        "Guardian Agent 识别到高风险诈骗证据，业务已熔断，等待人工反诈复核。",
        automatic=True,
    )
    run.response_text = "青穗盾已阻断该操作：发现多项高风险诈骗特征，未创建转账或其他业务指令，已转人工复核。"
    await guardian_service.persist_receipt(session, run)
    await session.commit()
    return run


async def drive_run(
    session: AsyncSession, run: AgentRun, conversation: AgentConversation
) -> AgentRun:
    if not verify_plan_hash(run.plan, run.plan_hash):
        run.status = "failed"
        run.error_code = "PLAN_INTEGRITY_FAILED"
        await append_audit_event(
            session,
            user_id=run.user_id,
            action="agent.plan.verify",
            outcome="denied",
            resource_type="agent_run",
            resource_id=run.id,
            reason_codes=["PLAN_INTEGRITY_FAILED"],
        )
        await session.commit()
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "PLAN_INTEGRITY_FAILED",
            "任务计划完整性校验失败。",
        )
    await complete_guardian_review(session, run)
    assessment = await guardian_service.assessment_for_run(session, run.id)
    if assessment and assessment.disposition == "block":
        return await drive_guardian_block(session, run)
    if run.intent == "fraud.assess":
        if assessment is None:
            raise RuntimeError("Guardian assessment missing for fraud.assess")
        result = {
            "fraud_assessment": {
                "score": assessment.scam_score,
                "disposition": assessment.disposition,
                "signals": assessment.signals,
                "summary": assessment.evidence_summary,
                "counterfactual": assessment.counterfactual,
            },
            "business_side_effects": False,
        }
        wording = "建议暂停操作并与官方客服独立核实。" if assessment.disposition == "step_up" else "未发现明显高风险话术，但仍请核对对方身份。"
        return await mark_completed(session, run, result, f"Guardian 反诈分 {assessment.scam_score}/100；{wording}")
    if run.intent in {"account.balance", "bill.summary", "bill.annual", "subscription.list", "card.list", "investment.holdings", "occasion.detect"}:
        return await run_green_query(session, run, conversation)
    if run.intent == "transfer.create":
        return await drive_transfer(session, run, conversation)
    if run.intent == "subscription.cancel":
        return await drive_subscription_cancel(session, run)
    if run.intent == "card.manage":
        return await drive_card_manage(session, run)
    if run.intent == "investment.recommend":
        return await drive_investment_recommendation(session, run)
    if run.intent == "occasion.plan":
        return await drive_occasion_plan(session, run)
    if run.intent in EXTENDED_WRITE_INTENTS:
        return await drive_extended_operation(session, run)
    step = await begin_step(session, run, "human_handoff")
    step.status = "paused"
    step.output_data = {"reason": "unsupported_intent"}
    await create_handoff(
        session, run, "当前意图不在 Agent 白名单内，需要人工处理。", automatic=True
    )
    return run


async def create_run(
    session: AsyncSession,
    user_id: str,
    message: str,
    channel: str,
    conversation_id: str | None,
    evidence_text: str | None = None,
    image_data_url: str | None = None,
) -> AgentRun:
    if conversation_id:
        conversation = await owned_conversation(session, user_id, conversation_id)
    else:
        conversation = AgentConversation(
            id=str(uuid4()),
            user_id=user_id,
            channel=channel,
            status="active",
            memory={},
        )
        session.add(conversation)
        await session.flush()

    prompt_inspection = inspect_untrusted_text(message)
    planning = await generate_plan(
        message,
        conversation.memory,
        user_id,
        adapter=DeterministicIntentAdapter() if prompt_inspection.suspicious else None,
    )
    intent_data = planning["intent_data"]
    if image_data_url:
        if not image_data_url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
            raise banking_service.domain_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "UNSUPPORTED_EVIDENCE_IMAGE",
                "证据图片仅支持 PNG、JPEG 或 WebP。",
            )
        if len(image_data_url) > 5_600_000:
            raise banking_service.domain_error(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "EVIDENCE_IMAGE_TOO_LARGE",
                "证据图片不能超过约 4 MB。",
            )
        try:
            evidence = await analyze_image(image_data_url, evidence_text)
        # The visual provider is optional. Any provider or schema failure must
        # degrade to deterministic text review instead of blocking the run.
        except Exception:  # noqa: BLE001
            fallback = text_evidence(evidence_text)
            evidence = EvidenceAnalysis(
                source_type="image",
                extracted_text=fallback.extracted_text,
                summary="图片已安全接收，视觉服务暂不可用，已降级为附加文字审查。",
                cues=[],
                provider="deterministic_fallback",
                fingerprint=hashlib.sha256(image_data_url.encode()).hexdigest(),
            )
    else:
        evidence = text_evidence(evidence_text)
    original_plan = list(planning["plan"])
    original_risk = highest_plan_risk(original_plan)
    if str(intent_data["intent"]) == "transfer.create":
        try:
            original_risk = "yellow" if Decimal(str(intent_data["slots"].get("amount"))) <= Decimal(1000) else "red"
        except (ArithmeticError, TypeError, ValueError):
            original_risk = "yellow"
    guardian_decision = await guardian_service.assess(
        session,
        user_id=user_id,
        intent=str(intent_data["intent"]),
        slots=dict(intent_data["slots"]),
        message=message,
        evidence=evidence,
        prompt_signals=prompt_inspection.signals,
        original_risk=original_risk,
    )
    enhanced_plan = guardian_plan(
        original_plan, str(intent_data["intent"]), guardian_decision.disposition
    )
    context = {
        "slots": intent_data["slots"],
        "missing_slots": intent_data["missing_slots"],
        "prompt_signals": prompt_inspection.signals,
        "guardian": {
            "score": guardian_decision.score,
            "disposition": guardian_decision.disposition,
            "original_risk": guardian_decision.original_risk,
            "effective_risk": guardian_decision.effective_risk,
        },
    }
    run = AgentRun(
        id=str(uuid4()),
        conversation_id=conversation.id,
        user_id=user_id,
        channel=channel,
        user_message=message,
        intent=str(intent_data["intent"]),
        confidence=Decimal(str(intent_data["confidence"])),
        model_provider=str(planning["model_provider"]),
        status="running",
        plan=enhanced_plan,
        plan_hash=hash_plan(enhanced_plan),
        context=context,
        version=1,
    )
    session.add(run)
    await session.flush()
    await guardian_service.create_assessment(
        session,
        run=run,
        decision=guardian_decision,
        evidence=evidence,
        banker_proposal={
            "intent": intent_data["intent"],
            "confidence": intent_data["confidence"],
            "slots": intent_data["slots"],
            "missing_slots": intent_data["missing_slots"],
            "original_plan_hash": planning["plan_hash"],
        },
    )
    await append_audit_event(
        session,
        user_id=user_id,
        action="agent.run.create",
        outcome="recorded",
        resource_type="agent_run",
        resource_id=run.id,
        reason_codes=["STRUCTURED_INTENT", "WHITELIST_DAG"],
        details={
            "intent": run.intent,
            "model_provider": run.model_provider,
            "prompt_signals": prompt_inspection.signals,
        },
    )
    await session.commit()
    return await drive_run(session, run, conversation)


async def merge_clarification(
    run: AgentRun,
    message: str,
    memory: dict[str, object],
) -> None:
    # A complete clarification such as "给妈妈转100元" must replace stale
    # slots from the original request instead of being shadowed by them.
    clarified = await DeterministicIntentAdapter().classify(message, memory, run.user_id)
    if clarified.intent == "unsupported":
        combined = f"{run.user_message}\n用户补充：{message}"
        adapter = get_intent_adapter()
        clarified = await adapter.classify(combined, memory, run.user_id)
    if clarified.intent != run.intent:
        combined = f"{run.user_message}\n用户补充：{message}"
        clarified = await DeterministicIntentAdapter().classify(
            combined, memory, run.user_id
        )
    if clarified.intent != run.intent:
        raise banking_service.domain_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "CLARIFICATION_INTENT_MISMATCH",
            "补充内容与当前业务不一致，请重新描述。",
        )
    slots = dict(run.context.get("slots", {}))
    slots.update({key: value for key, value in clarified.slots.items() if value is not None})
    run.context = {
        **run.context,
        "slots": slots,
        "missing_slots": clarified.missing_slots,
    }


async def resume_run(
    session: AsyncSession,
    user_id: str,
    run_id: str,
    payload: AgentResumeRequest,
) -> AgentRun:
    run = await owned_run(session, user_id, run_id, lock=True)
    if run.status == "human_review":
        raise banking_service.domain_error(
            status.HTTP_409_CONFLICT,
            "HUMAN_REVIEW_REQUIRED",
            "任务正在人工接管中。",
        )
    if run.status in TERMINAL_STATUSES:
        return run
    if not verify_plan_hash(run.plan, run.plan_hash):
        return await drive_run(
            session,
            run,
            await owned_conversation(session, user_id, run.conversation_id),
        )

    conversation = await owned_conversation(session, user_id, run.conversation_id)
    if run.status == "waiting_clarification":
        if payload.clarification_message:
            inspection = inspect_untrusted_text(payload.clarification_message)
            if inspection.suspicious:
                await create_handoff(
                    session,
                    run,
                    "补充信息包含疑似指令覆盖或权限绕过内容，已自动转交人工。",
                    automatic=True,
                )
                return run
        if payload.selected_payee_id:
            payee = await session.scalar(
                select(Payee).where(
                    Payee.id == payload.selected_payee_id,
                    Payee.owner_user_id == user_id,
                )
            )
            if payee is None:
                raise banking_service.domain_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "INVALID_PAYEE_SELECTION",
                    "选择的收款人无效。",
                )
            update_context(run, payee_id=payee.id, payee_name=payee.name)
            update_memory(
                conversation, last_payee_id=payee.id, last_payee_name=payee.name
            )
            step = await begin_step(session, run, "resolve_payee")
            await complete_step(
                session,
                step,
                {
                    "payee_id": payee.id,
                    "name": payee.name,
                    "account_masked": payee.account_masked,
                },
            )
        elif payload.selected_subscription_id:
            subscription = await session.scalar(
                select(Subscription).where(
                    Subscription.id == payload.selected_subscription_id,
                    Subscription.user_id == user_id,
                    Subscription.status == "active",
                )
            )
            if subscription is None:
                raise banking_service.domain_error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "INVALID_SUBSCRIPTION_SELECTION",
                    "选择的订阅无效。",
                )
            update_context(
                run,
                subscription_id=subscription.id,
                subscription_merchant=subscription.merchant,
                subscription_product=subscription.product_name,
                subscription_amount=str(subscription.amount),
            )
            step = await begin_step(session, run, "resolve_subscription")
            await complete_step(
                session,
                step,
                {
                    "subscription_id": subscription.id,
                    "merchant": subscription.merchant,
                    "product_name": subscription.product_name,
                },
            )
        elif payload.clarification_message:
            await merge_clarification(
                run, payload.clarification_message, conversation.memory
            )
            paused_step = await session.scalar(
                select(AgentStep).where(
                    AgentStep.run_id == run.id, AgentStep.status == "paused"
                )
            )
            if paused_step is not None:
                paused_step.status = "skipped"
                paused_step.finished_at = datetime.now(UTC)
        else:
            raise banking_service.domain_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "CLARIFICATION_REQUIRED",
                "请补充信息或选择收款人。",
            )
        run.status = "running"
        run.pending_action = None
        run.version += 1
        await session.commit()
        return await drive_run(session, run, conversation)

    if run.status == "waiting_confirmation":
        if payload.confirmed is None:
            raise banking_service.domain_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "EXPLICIT_CONFIRMATION_REQUIRED",
                "请明确确认或拒绝本次转账。",
            )
        if run.intent in EXTENDED_WRITE_INTENTS:
            gate = await begin_step(session, run, "authorization_gate")
            await complete_step(session, gate, {"confirmed": payload.confirmed})
            await append_audit_event(
                session, user_id=user_id, action=f"{run.intent}.confirm",
                outcome="allowed" if payload.confirmed else "denied", risk_level="yellow",
                resource_type="agent_run", resource_id=run.id,
                reason_codes=["USER_CONFIRMED" if payload.confirmed else "USER_REJECTED"],
            )
            if not payload.confirmed:
                run.status = "cancelled"
                run.pending_action = None
                run.response_text = "你已取消本次操作，系统未产生业务变更。"
                await session.commit()
                return run
            run.status = "running"
            run.pending_action = None
            await session.commit()
            return await execute_extended_operation(session, run)
        if run.intent == "occasion.plan":
            gate = await begin_step(session, run, "authorization_gate")
            await complete_step(session, gate, {"confirmed": payload.confirmed})
            await append_audit_event(
                session,
                user_id=user_id,
                action="occasion.user.confirm",
                outcome="allowed" if payload.confirmed else "denied",
                risk_level="yellow",
                resource_type="agent_run",
                resource_id=run.id,
                reason_codes=["USER_CONFIRMED" if payload.confirmed else "USER_REJECTED"],
            )
            if not payload.confirmed:
                run.status = "cancelled"
                run.pending_action = None
                run.response_text = "你已取消计划，未预留资金或创建任务。"
                await session.commit()
                return run
            run.status = "running"
            run.pending_action = None
            await session.commit()
            return await execute_occasion_plan(session, run)

        if run.intent == "subscription.cancel":
            gate = await begin_step(session, run, "authorization_gate")
            await complete_step(session, gate, {"confirmed": payload.confirmed})
            await append_audit_event(
                session,
                user_id=user_id,
                action="subscription.user.confirm",
                outcome="allowed" if payload.confirmed else "denied",
                risk_level="yellow",
                resource_type="subscription",
                resource_id=str(run.context["subscription_id"]),
                reason_codes=["USER_CONFIRMED" if payload.confirmed else "USER_REJECTED"],
            )
            if not payload.confirmed:
                run.status = "cancelled"
                run.pending_action = None
                run.response_text = "你已保留该订阅，本次未做修改。"
                await session.commit()
                return run
            run.status = "running"
            run.pending_action = None
            await session.commit()
            return await execute_subscription_cancellation(session, run)

        draft = await security_service.confirm_transfer(
            session, user_id, str(run.context["draft_id"]), payload.confirmed
        )
        gate = await begin_step(session, run, "authorization_gate")
        await complete_step(
            session, gate, {"confirmed": payload.confirmed, "draft_status": draft.status}
        )
        if not payload.confirmed:
            run.status = "cancelled"
            run.pending_action = None
            run.response_text = "你已取消本次转账。"
            await session.commit()
            return run
        run.status = "running"
        run.pending_action = None
        await session.commit()
        return await execute_authorized_transfer(session, run)

    if run.status == "waiting_auth":
        if payload.auth_code is None:
            raise banking_service.domain_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "AUTH_CODE_REQUIRED",
                "请输入六位短信验证码。",
            )
        if run.intent in EXTENDED_WRITE_INTENTS:
            challenge = await security_service.verify_operation_auth_challenge(
                session, user_id, str(run.context["challenge_id"]), payload.auth_code
            )
            gate = await begin_step(session, run, "authorization_gate", input_data={"auth_code": payload.auth_code})
            await complete_step(session, gate, {"challenge_status": challenge.status})
            run.status = "running"
            run.pending_action = None
            await session.commit()
            return await execute_extended_operation(session, run)
        if run.intent == "card.manage":
            challenge = await security_service.verify_operation_auth_challenge(
                session,
                user_id,
                str(run.context["challenge_id"]),
                payload.auth_code,
            )
            gate = await begin_step(
                session,
                run,
                "authorization_gate",
                input_data={"auth_code": payload.auth_code},
            )
            await complete_step(
                session, gate, {"challenge_status": challenge.status}
            )
            run.status = "running"
            run.pending_action = None
            await session.commit()
            return await execute_card_action(session, run)

        challenge, draft = await security_service.verify_auth_challenge(
            session,
            user_id,
            str(run.context["challenge_id"]),
            payload.auth_code,
        )
        gate = await begin_step(
            session, run, "authorization_gate", input_data={"auth_code": payload.auth_code}
        )
        await complete_step(
            session,
            gate,
            {"challenge_status": challenge.status, "draft_status": draft.status},
        )
        run.status = "running"
        run.pending_action = None
        await session.commit()
        return await execute_authorized_transfer(session, run)

    raise banking_service.domain_error(
        status.HTTP_409_CONFLICT,
        "AGENT_RUN_NOT_PAUSED",
        "当前运行不需要恢复输入。",
    )


async def resolve_handoff(
    session: AsyncSession,
    user_id: str,
    run_id: str,
    action: str,
    note: str,
) -> tuple[AgentRun, AgentHandoff]:
    run = await owned_run(session, user_id, run_id, lock=True)
    handoff = await active_handoff(session, run.id)
    if handoff is None:
        raise banking_service.domain_error(
            status.HTTP_404_NOT_FOUND,
            "AGENT_HANDOFF_NOT_FOUND",
            "没有待处理的人工接管请求。",
        )
    handoff.status = "resolved"
    handoff.resolution = note
    handoff.resolved_at = datetime.now(UTC)
    if action == "cancel":
        run.status = "cancelled"
    elif action == "complete":
        run.status = "completed"
        run.result = {"handled_by": "human", "note": note}
    else:
        run.status = handoff.resume_status
    run.pending_action = None
    run.response_text = {
        "cancel": "人工已取消任务。",
        "complete": note,
        "resume": "人工已允许任务恢复。",
    }[action]
    run.version += 1
    await append_audit_event(
        session,
        user_id=user_id,
        action="agent.handoff.resolve",
        outcome="denied" if action == "cancel" else "allowed",
        resource_type="agent_run",
        resource_id=run.id,
        reason_codes=[
            {
                "cancel": "HUMAN_CANCELLED",
                "complete": "HUMAN_COMPLETED",
                "resume": "HUMAN_RESUMED",
            }[action]
        ],
        details={"note": note},
    )
    await session.commit()
    if action == "resume" and run.status == "running":
        conversation = await owned_conversation(session, user_id, run.conversation_id)
        run = await drive_run(session, run, conversation)
    return run, handoff
