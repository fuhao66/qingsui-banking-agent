import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.vision import EvidenceAnalysis
from app.db.models import Account, AgentRun, GuardianAssessment, Payee, Transaction
from app.services.audit import append_audit_event

RISK_RANK = {"green": 1, "yellow": 2, "red": 3}


@dataclass(frozen=True)
class GuardianDecision:
    score: int
    disposition: str
    original_risk: str
    effective_risk: str
    signals: list[dict[str, object]]
    counterfactual: dict[str, object]


PATTERNS: tuple[tuple[str, str, int, re.Pattern[str]], ...] = (
    ("SAFE_ACCOUNT", "要求转入所谓安全账户", 35, re.compile(r"安全账户|监管账户|审查账户")),
    ("SECRECY_PRESSURE", "要求保密或切断求助", 22, re.compile(r"不要告诉|不能告诉|保密|别联系家人|别报警")),
    ("URGENCY_PRESSURE", "制造紧迫感", 14, re.compile(r"马上|立即|立刻|最后.{0,4}分钟|否则.{0,10}(冻结|抓捕|起诉)")),
    ("IMPERSONATION", "冒充权威机构或平台客服", 16, re.compile(r"公安|警察|检察院|法院|客服|银行工作人员|平台专员")),
    ("REMOTE_CONTROL", "诱导共享屏幕或远程控制", 28, re.compile(r"共享屏幕|远程控制|下载.{0,8}(会议|远程|控制)|开启录屏")),
    ("CREDENTIAL_REQUEST", "索取验证码或账户凭证", 28, re.compile(r"验证码|OTP|密码|U盾|屏幕共享" , re.IGNORECASE)),
    ("REFUND_OR_CREDIT_SCAM", "退款、征信或刷流水诱导", 18, re.compile(r"退款|征信|刷流水|保证金|解冻金|认证金")),
)


def static_signal_assessment(
    text: str, prompt_signals: list[str] | None = None
) -> tuple[int, str, list[dict[str, object]]]:
    """Pure, database-free Guardian check used by evals and as the first review layer."""
    signals: list[dict[str, object]] = []
    for code, label, weight, pattern in PATTERNS:
        match = pattern.search(text[:8000])
        if match:
            signals.append({"code": code, "label": label, "weight": weight, "evidence": match.group(0)[:80]})
    if prompt_signals:
        signals.append({"code": "PROMPT_INJECTION", "label": "检测到试图覆盖系统或权限规则的指令", "weight": 45, "evidence": ",".join(prompt_signals)[:80]})
    score = min(100, sum(int(item["weight"]) for item in signals))
    disposition = "block" if score >= 65 or prompt_signals else "step_up" if score >= 24 else "allow"
    return score, disposition, signals


def _amount(slots: dict[str, object]) -> Decimal | None:
    for key in ("amount", "investment_amount", "budget"):
        try:
            if slots.get(key) is not None:
                return Decimal(str(slots[key]))
        except (ArithmeticError, TypeError, ValueError):
            return None
    return None


async def assess(
    session: AsyncSession,
    *,
    user_id: str,
    intent: str,
    slots: dict[str, object],
    message: str,
    evidence: EvidenceAnalysis,
    prompt_signals: list[str],
    original_risk: str,
) -> GuardianDecision:
    combined = f"{message}\n{evidence.extracted_text}"[:8000]
    _, _, signals = static_signal_assessment(combined, prompt_signals)
    seen: set[str] = {str(item["code"]) for item in signals}

    def add(code: str, label: str, weight: int, evidence_value: str) -> None:
        if code not in seen:
            seen.add(code)
            signals.append({"code": code, "label": label, "weight": weight, "evidence": evidence_value[:80]})

    for cue in evidence.cues[:8]:
        add(f"VISION_CUE_{len(seen) + 1}", "视觉模型识别到风险话术", 8, cue)

    if intent.startswith("transfer"):
        query = str(slots.get("recipient_query") or "").strip()
        if query:
            known = await session.scalar(
                select(Payee.id).where(
                    Payee.owner_user_id == user_id,
                    or_(Payee.name.ilike(f"%{query}%"), Payee.alias.ilike(f"%{query}%"), Payee.phone_last4 == query[-4:]),
                ).limit(1)
            )
            if not known:
                add("UNKNOWN_PAYEE", "收款人不在历史联系人中", 24, query)

        amount = _amount(slots)
        if amount is not None:
            average = await session.scalar(
                select(func.avg(Transaction.amount))
                .join(Account, Account.id == Transaction.account_id)
                .where(Account.user_id == user_id, Transaction.direction == "debit", Transaction.status == "completed")
            )
            baseline = Decimal(str(average or 0))
            if amount >= Decimal(5000) or (baseline > 0 and amount >= baseline * 3):
                add("AMOUNT_ANOMALY", "金额显著高于历史支出基线", 16, f"{amount:.2f} vs baseline {baseline:.2f}")

    score = min(100, sum(int(signal["weight"]) for signal in signals))
    if score >= 65 or "PROMPT_INJECTION" in seen:
        disposition = "block"
        effective = "red"
    elif score >= 24:
        disposition = "step_up"
        effective = "red"
    else:
        disposition = "allow"
        effective = original_risk

    removed = [signal["label"] for signal in signals]
    counterfactual = {
        "current": f"当前因 {len(signals)} 项风险证据，策略为 {disposition}。",
        "without_signals": "若移除高风险话术、使用历史联系人且金额符合日常基线，操作将按常规权限执行。",
        "changed_factors": removed[:5],
    }
    return GuardianDecision(score, disposition, original_risk, effective, signals, counterfactual)


async def create_assessment(
    session: AsyncSession,
    *,
    run: AgentRun,
    decision: GuardianDecision,
    evidence: EvidenceAnalysis,
    banker_proposal: dict[str, object],
) -> GuardianAssessment:
    row = GuardianAssessment(
        id=str(uuid4()), run_id=run.id, user_id=run.user_id,
        source_type=evidence.source_type, model_provider=evidence.provider,
        scam_score=decision.score, disposition=decision.disposition,
        original_risk=decision.original_risk, effective_risk=decision.effective_risk,
        signals=decision.signals, evidence_summary=evidence.summary or None,
        evidence_fingerprint=evidence.fingerprint, banker_proposal=banker_proposal,
        counterfactual=decision.counterfactual, decision_receipt={}, receipt_hash=None,
    )
    session.add(row)
    await append_audit_event(
        session, user_id=run.user_id, action="guardian.risk.assess",
        outcome="denied" if decision.disposition == "block" else "recorded",
        risk_level=decision.effective_risk, resource_type="guardian_assessment",
        resource_id=row.id, correlation_id=run.id,
        reason_codes=[str(item["code"]) for item in decision.signals] or ["NO_FRAUD_SIGNALS"],
        details={"score": decision.score, "disposition": decision.disposition, "source_type": evidence.source_type},
    )
    await session.flush()
    return row


async def assessment_for_run(session: AsyncSession, run_id: str) -> GuardianAssessment | None:
    return await session.scalar(select(GuardianAssessment).where(GuardianAssessment.run_id == run_id))


async def persist_receipt(session: AsyncSession, run: AgentRun) -> GuardianAssessment | None:
    assessment = await assessment_for_run(session, run.id)
    if not assessment:
        return None
    receipt = {
        "version": "guardian-receipt-1.0",
        "run_id": run.id,
        "intent": run.intent,
        "run_status": run.status,
        "plan_hash": run.plan_hash,
        "banker_proposal": assessment.banker_proposal,
        "guardian": {
            "score": assessment.scam_score,
            "disposition": assessment.disposition,
            "signals": assessment.signals,
            "original_risk": assessment.original_risk,
            "effective_risk": assessment.effective_risk,
            "evidence_fingerprint": assessment.evidence_fingerprint,
        },
        "authorization": {
            "challenge_created": bool(run.context.get("challenge_id")),
            "policy_decision_id": run.context.get("policy_decision_id"),
        },
        "result": run.result,
        "error_code": run.error_code,
    }
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assessment.decision_receipt = receipt
    assessment.receipt_hash = hashlib.sha256(canonical.encode()).hexdigest()
    await session.flush()
    return assessment
