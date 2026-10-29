import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import Base
from app.db.models import (
    Account,
    AgentConversation,
    AgentHandoff,
    AgentRun,
    AgentStep,
    AuditEvent,
    AuthChallenge,
    BankCard,
    BusinessOperation,
    GuardianAssessment,
    OperationAuthChallenge,
    Payee,
    PolicyDecision,
    ScheduledTask,
    SecurityState,
    Subscription,
    Transaction,
    TransferDraft,
    TransferExecution,
)
from app.db.seed import seed_demo_data
from app.domain.constants import DEMO_USER_ID
from app.services.audit import append_audit_event

reset_lock = asyncio.Lock()


async def reset_user_sandbox(session: AsyncSession, user_id: str) -> None:
    run_ids = select(AgentRun.id).where(AgentRun.user_id == user_id)
    draft_ids = select(TransferDraft.id).where(TransferDraft.user_id == user_id)
    account_ids = select(Account.id).where(Account.user_id == user_id)
    await session.execute(delete(ScheduledTask).where(ScheduledTask.user_id == user_id))
    await session.execute(delete(BusinessOperation).where(BusinessOperation.user_id == user_id))
    await session.execute(delete(GuardianAssessment).where(GuardianAssessment.user_id == user_id))
    await session.execute(delete(AgentStep).where(AgentStep.run_id.in_(run_ids)))
    await session.execute(delete(AgentHandoff).where(AgentHandoff.user_id == user_id))
    await session.execute(delete(AgentRun).where(AgentRun.user_id == user_id))
    await session.execute(delete(AgentConversation).where(AgentConversation.user_id == user_id))
    await session.execute(delete(TransferExecution).where(TransferExecution.user_id == user_id))
    await session.execute(delete(AuthChallenge).where(AuthChallenge.user_id == user_id))
    await session.execute(
        delete(OperationAuthChallenge).where(OperationAuthChallenge.user_id == user_id)
    )
    await session.execute(delete(PolicyDecision).where(PolicyDecision.user_id == user_id))
    await session.execute(delete(TransferDraft).where(TransferDraft.id.in_(draft_ids)))
    await session.execute(delete(AuditEvent).where(AuditEvent.user_id == user_id))
    await session.execute(delete(Transaction).where(Transaction.account_id.in_(account_ids)))

    template_accounts = list(
        await session.scalars(select(Account).where(Account.user_id == DEMO_USER_ID))
    )
    user_accounts = list(await session.scalars(select(Account).where(Account.user_id == user_id)))
    template_by_name = {item.name: item for item in template_accounts}
    user_by_name = {item.name: item for item in user_accounts}
    for name, account in user_by_name.items():
        template = template_by_name[name]
        account.balance = template.balance
        account.status = "active"

    template_subscriptions = list(
        await session.scalars(select(Subscription).where(Subscription.user_id == DEMO_USER_ID))
    )
    user_subscriptions = list(
        await session.scalars(select(Subscription).where(Subscription.user_id == user_id))
    )
    subscription_templates = {item.merchant: item for item in template_subscriptions}
    for item in user_subscriptions:
        template = subscription_templates[item.merchant]
        item.status = "active"
        item.next_charge_at = template.next_charge_at
        item.last_charge_at = template.last_charge_at

    cards = await session.scalars(select(BankCard).where(BankCard.user_id == user_id))
    for card in cards:
        card.status = "active"
        template = await session.scalar(select(BankCard).where(BankCard.user_id == DEMO_USER_ID, BankCard.last4 == card.last4))
        if template:
            card.daily_limit = template.daily_limit
            card.transaction_limit = template.transaction_limit
            card.online_transactions_enabled = template.online_transactions_enabled

    template_payees = list(
        await session.scalars(select(Payee).where(Payee.owner_user_id == DEMO_USER_ID))
    )
    payee_templates = {(item.name, item.phone_last4): item for item in template_payees}
    payees = await session.scalars(select(Payee).where(Payee.owner_user_id == user_id))
    for payee in payees:
        payee.last_transfer_at = payee_templates[(payee.name, payee.phone_last4)].last_transfer_at

    template_account_names = {item.id: item.name for item in template_accounts}
    template_transactions = await session.scalars(
        select(Transaction).where(Transaction.account_id.in_([item.id for item in template_accounts]))
    )
    for source in template_transactions:
        transaction_id = str(uuid4())
        target_account = user_by_name[template_account_names[source.account_id]]
        session.add(
            Transaction(
                id=transaction_id,
                account_id=target_account.id,
                direction=source.direction,
                category=source.category,
                amount=source.amount,
                currency=source.currency,
                merchant=source.merchant,
                counterparty_name=source.counterparty_name,
                description=source.description,
                status=source.status,
                occurred_at=source.occurred_at,
                is_recurring=source.is_recurring,
                risk_flag=source.risk_flag,
                external_reference=f"RESET-{user_id[:8]}-{transaction_id[:12]}",
            )
        )
    security_state = await session.get(SecurityState, user_id)
    if security_state:
        security_state.consecutive_failures = 0
        security_state.locked_until = None
        security_state.last_failure_at = None
    await session.flush()


async def reset_demo_data(session: AsyncSession, user_id: str) -> tuple[datetime, str]:
    if settings.app_env != "development" and not settings.public_demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DEMO_RESET_DISABLED",
                "message": "数据重置仅在 development 演示环境开放。",
            },
        )

    async with reset_lock:
        try:
            if settings.public_demo_mode and user_id != DEMO_USER_ID:
                await reset_user_sandbox(session, user_id)
            else:
                for table in reversed(Base.metadata.sorted_tables):
                    await session.execute(delete(table))
                await session.commit()
                await seed_demo_data(session)
            reset_at = datetime.now(UTC)
            event = await append_audit_event(
                session,
                user_id=user_id,
                action="demo.data.reset",
                outcome="recorded",
                resource_type="demo_environment",
                resource_id="banking-agent-demo",
                reason_codes=[
                    "USER_SCOPED" if settings.public_demo_mode else "DEVELOPMENT_ONLY",
                    "EXPLICIT_CONFIRMATION",
                ],
                details={"reset_at": reset_at.isoformat()},
            )
            await session.commit()
            return reset_at, event.id
        except Exception:
            await session.rollback()
            raise
