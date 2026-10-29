import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Account,
    AuthChallenge,
    OperationAuthChallenge,
    Payee,
    PolicyDecision,
    SecurityState,
    Transaction,
    TransferDraft,
    TransferExecution,
    User,
)
from app.security.prompt_guard import inspect_untrusted_text
from app.services.audit import append_audit_event
from app.services.banking import CENT, domain_error

POLICY_VERSION = "transfer-policy-2026.09"
TRANSFER_DAILY_THRESHOLD = Decimal("1000.00")


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def challenge_digest(challenge_id: str, code: str) -> str:
    message = f"{challenge_id}:{code}".encode()
    return hmac.new(
        settings.security_hmac_secret.encode(), message, hashlib.sha256
    ).hexdigest()


async def get_security_state(
    session: AsyncSession, user_id: str, *, lock: bool = False
) -> SecurityState:
    statement = select(SecurityState).where(SecurityState.user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    state_row = await session.scalar(statement)
    if state_row is None:
        state_row = SecurityState(user_id=user_id, consecutive_failures=0)
        session.add(state_row)
        await session.flush()
    return state_row


async def assert_not_locked(session: AsyncSession, user_id: str) -> SecurityState:
    state_row = await get_security_state(session, user_id, lock=True)
    now = datetime.now(UTC)
    if state_row.locked_until is not None:
        locked_until = aware_utc(state_row.locked_until)
        if locked_until > now:
            await append_audit_event(
                session,
                user_id=user_id,
                action="security.fuse.block",
                outcome="denied",
                resource_type="user_security_state",
                resource_id=user_id,
                reason_codes=["SECURITY_LOCKED"],
                details={"locked_until": locked_until.isoformat()},
            )
            await session.commit()
            raise domain_error(
                status.HTTP_423_LOCKED,
                "SECURITY_LOCKED",
                f"连续验证失败，安全锁定至 {locked_until.isoformat()}。",
            )
        state_row.locked_until = None
        state_row.consecutive_failures = 0
        await session.flush()
    return state_row


async def owned_draft(
    session: AsyncSession, user_id: str, draft_id: str, *, lock: bool = False
) -> TransferDraft:
    statement = select(TransferDraft).where(
        TransferDraft.id == draft_id, TransferDraft.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    draft = await session.scalar(statement)
    if draft is None:
        raise domain_error(
            status.HTTP_404_NOT_FOUND,
            "TRANSFER_DRAFT_NOT_FOUND",
            "转账草案不存在。",
        )
    return draft


async def daily_executed_total(
    session: AsyncSession, user_id: str, now: datetime
) -> Decimal:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = await session.scalar(
        select(func.sum(TransferExecution.amount)).where(
            TransferExecution.user_id == user_id,
            TransferExecution.status == "succeeded",
            TransferExecution.created_at >= day_start,
        )
    )
    return Decimal(total or 0).quantize(CENT)


def next_action_for_status(draft_status: str) -> str:
    return {
        "awaiting_confirmation": "confirm",
        "awaiting_auth": "create_auth_challenge",
        "approved": "execute",
        "executed": "completed",
        "cancelled": "none",
    }.get(draft_status, "prepare")


async def evaluate_transfer_policy(
    session: AsyncSession, user_id: str, draft_id: str
) -> tuple[TransferDraft, PolicyDecision]:
    await assert_not_locked(session, user_id)
    draft = await owned_draft(session, user_id, draft_id, lock=True)
    existing = await session.scalar(
        select(PolicyDecision).where(PolicyDecision.draft_id == draft.id)
    )
    if existing is not None:
        return draft, existing

    now = datetime.now(UTC)
    if aware_utc(draft.expires_at) <= now:
        draft.status = "expired"
        await append_audit_event(
            session,
            user_id=user_id,
            action="transfer.policy.evaluate",
            outcome="denied",
            resource_type="transfer_draft",
            resource_id=draft.id,
            reason_codes=["DRAFT_EXPIRED"],
        )
        await session.commit()
        raise domain_error(status.HTTP_410_GONE, "DRAFT_EXPIRED", "转账草案已过期。")
    if draft.status != "pending_policy":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "INVALID_DRAFT_STATE",
            f"当前状态 {draft.status} 不允许策略评估。",
        )

    daily_before = await daily_executed_total(session, user_id, now)
    projected = (daily_before + draft.amount).quantize(CENT)
    prompt_inspection = inspect_untrusted_text(draft.memo)
    reason_codes = ["TRANSFER_REQUIRES_CONFIRMATION"]
    risk_level = "yellow"
    required_action = "confirmation"
    if projected > TRANSFER_DAILY_THRESHOLD:
        risk_level = "red"
        required_action = "strong_auth"
        reason_codes.append("DAILY_TRANSFER_THRESHOLD_EXCEEDED")
    else:
        reason_codes.append("DAILY_TRANSFER_WITHIN_THRESHOLD")
    if prompt_inspection.suspicious:
        risk_level = "red"
        required_action = "strong_auth"
        reason_codes.append("UNTRUSTED_INSTRUCTION_DETECTED")

    decision = PolicyDecision(
        id=str(uuid4()),
        user_id=user_id,
        draft_id=draft.id,
        risk_level=risk_level,
        required_action=required_action,
        policy_version=POLICY_VERSION,
        daily_total_before=daily_before,
        projected_daily_total=projected,
        reason_codes=reason_codes,
        prompt_signals=prompt_inspection.signals,
    )
    draft.status = (
        "awaiting_confirmation" if risk_level == "yellow" else "awaiting_auth"
    )
    session.add(decision)
    await append_audit_event(
        session,
        user_id=user_id,
        action="transfer.policy.evaluate",
        outcome="allowed",
        risk_level=risk_level,
        resource_type="transfer_draft",
        resource_id=draft.id,
        reason_codes=reason_codes,
        details={
            "amount": str(draft.amount),
            "daily_total_before": str(daily_before),
            "projected_daily_total": str(projected),
            "prompt_signals": prompt_inspection.signals,
        },
    )
    await session.commit()
    await session.refresh(decision)
    return draft, decision


async def confirm_transfer(
    session: AsyncSession, user_id: str, draft_id: str, confirmed: bool
) -> TransferDraft:
    await assert_not_locked(session, user_id)
    draft = await owned_draft(session, user_id, draft_id, lock=True)
    decision = await session.scalar(
        select(PolicyDecision).where(PolicyDecision.draft_id == draft.id)
    )
    if decision is None or decision.risk_level != "yellow":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "CONFIRMATION_NOT_ALLOWED",
            "该操作不是黄色确认流程。",
        )
    if draft.status == "approved" and confirmed:
        return draft
    if draft.status != "awaiting_confirmation":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "INVALID_DRAFT_STATE",
            f"当前状态 {draft.status} 不允许确认。",
        )

    draft.status = "approved" if confirmed else "cancelled"
    await append_audit_event(
        session,
        user_id=user_id,
        action="transfer.user.confirm",
        outcome="allowed" if confirmed else "denied",
        risk_level="yellow",
        resource_type="transfer_draft",
        resource_id=draft.id,
        reason_codes=["USER_CONFIRMED" if confirmed else "USER_REJECTED"],
    )
    await session.commit()
    return draft


async def create_auth_challenge(
    session: AsyncSession, user_id: str, draft_id: str
) -> AuthChallenge:
    await assert_not_locked(session, user_id)
    draft = await owned_draft(session, user_id, draft_id, lock=True)
    decision = await session.scalar(
        select(PolicyDecision).where(PolicyDecision.draft_id == draft.id)
    )
    if decision is None or decision.risk_level != "red":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "STRONG_AUTH_NOT_REQUIRED",
            "该操作不需要强验证。",
        )
    if draft.status != "awaiting_auth":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "INVALID_DRAFT_STATE",
            f"当前状态 {draft.status} 不允许发起强验证。",
        )

    now = datetime.now(UTC)
    existing = await session.scalar(
        select(AuthChallenge)
        .where(
            AuthChallenge.draft_id == draft.id,
            AuthChallenge.user_id == user_id,
            AuthChallenge.status == "pending",
        )
        .order_by(AuthChallenge.created_at.desc())
        .limit(1)
    )
    if existing is not None and aware_utc(existing.expires_at) > now:
        return existing
    if existing is not None:
        existing.status = "expired"

    user = await session.get(User, user_id)
    if user is None:
        raise domain_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "用户不存在。")
    challenge_id = str(uuid4())
    challenge = AuthChallenge(
        id=challenge_id,
        user_id=user_id,
        draft_id=draft.id,
        method="sms_otp",
        destination_masked=user.phone_masked,
        code_digest=challenge_digest(challenge_id, settings.demo_otp_code),
        status="pending",
        attempts=0,
        expires_at=now + timedelta(minutes=settings.auth_challenge_minutes),
    )
    session.add(challenge)
    await append_audit_event(
        session,
        user_id=user_id,
        action="auth.challenge.create",
        outcome="recorded",
        risk_level="red",
        resource_type="auth_challenge",
        resource_id=challenge.id,
        reason_codes=["SMS_OTP_REQUIRED"],
        details={"destination": user.phone_masked, "otp_code": settings.demo_otp_code},
    )
    await session.commit()
    await session.refresh(challenge)
    return challenge


async def verify_auth_challenge(
    session: AsyncSession, user_id: str, challenge_id: str, code: str
) -> tuple[AuthChallenge, TransferDraft]:
    state_row = await assert_not_locked(session, user_id)
    challenge = await session.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.id == challenge_id, AuthChallenge.user_id == user_id)
        .with_for_update()
    )
    if challenge is None:
        raise domain_error(
            status.HTTP_404_NOT_FOUND, "AUTH_CHALLENGE_NOT_FOUND", "验证挑战不存在。"
        )
    draft = await owned_draft(session, user_id, challenge.draft_id, lock=True)
    if challenge.status == "verified":
        return challenge, draft
    if challenge.status != "pending":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "AUTH_CHALLENGE_NOT_ACTIVE",
            "验证挑战已失效。",
        )

    now = datetime.now(UTC)
    if aware_utc(challenge.expires_at) <= now:
        challenge.status = "expired"
        await append_audit_event(
            session,
            user_id=user_id,
            action="auth.challenge.verify",
            outcome="denied",
            risk_level="red",
            resource_type="auth_challenge",
            resource_id=challenge.id,
            reason_codes=["AUTH_CHALLENGE_EXPIRED"],
        )
        await session.commit()
        raise domain_error(
            status.HTTP_410_GONE, "AUTH_CHALLENGE_EXPIRED", "验证码已过期。"
        )

    supplied_digest = challenge_digest(challenge.id, code)
    if not hmac.compare_digest(supplied_digest, challenge.code_digest):
        challenge.attempts += 1
        state_row.consecutive_failures += 1
        state_row.last_failure_at = now
        is_locked = state_row.consecutive_failures >= settings.auth_max_failures
        if is_locked:
            state_row.locked_until = now + timedelta(minutes=settings.auth_lock_minutes)
            challenge.status = "locked"
        await append_audit_event(
            session,
            user_id=user_id,
            action="auth.challenge.verify",
            outcome="failed",
            risk_level="red",
            resource_type="auth_challenge",
            resource_id=challenge.id,
            reason_codes=[
                "AUTH_FAILED",
                *(["SECURITY_FUSE_OPEN"] if is_locked else []),
            ],
            details={"otp_code": code, "attempt": challenge.attempts},
        )
        await session.commit()
        if is_locked:
            raise domain_error(
                status.HTTP_423_LOCKED,
                "SECURITY_FUSE_OPEN",
                "连续验证失败，账户已临时锁定。",
            )
        raise domain_error(
            status.HTTP_401_UNAUTHORIZED, "INVALID_AUTH_CODE", "验证码错误。"
        )

    challenge.status = "verified"
    challenge.verified_at = now
    draft.status = "approved"
    state_row.consecutive_failures = 0
    state_row.last_failure_at = None
    state_row.locked_until = None
    await append_audit_event(
        session,
        user_id=user_id,
        action="auth.challenge.verify",
        outcome="allowed",
        risk_level="red",
        resource_type="auth_challenge",
        resource_id=challenge.id,
        reason_codes=["STRONG_AUTH_VERIFIED"],
    )
    await session.commit()
    return challenge, draft


async def create_operation_auth_challenge(
    session: AsyncSession,
    user_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
) -> OperationAuthChallenge:
    await assert_not_locked(session, user_id)
    now = datetime.now(UTC)
    existing = await session.scalar(
        select(OperationAuthChallenge)
        .where(
            OperationAuthChallenge.user_id == user_id,
            OperationAuthChallenge.resource_type == resource_type,
            OperationAuthChallenge.resource_id == resource_id,
            OperationAuthChallenge.action == action,
            OperationAuthChallenge.status == "pending",
        )
        .order_by(OperationAuthChallenge.created_at.desc())
        .limit(1)
    )
    if existing is not None and aware_utc(existing.expires_at) > now:
        return existing
    if existing is not None:
        existing.status = "expired"

    user = await session.get(User, user_id)
    if user is None:
        raise domain_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "用户不存在。")
    challenge_id = str(uuid4())
    challenge = OperationAuthChallenge(
        id=challenge_id,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        method="sms_otp",
        destination_masked=user.phone_masked,
        code_digest=challenge_digest(challenge_id, settings.demo_otp_code),
        status="pending",
        attempts=0,
        expires_at=now + timedelta(minutes=settings.auth_challenge_minutes),
    )
    session.add(challenge)
    await append_audit_event(
        session,
        user_id=user_id,
        action="auth.operation.create",
        outcome="recorded",
        risk_level="red",
        resource_type="operation_auth_challenge",
        resource_id=challenge.id,
        reason_codes=["SMS_OTP_REQUIRED", action.upper()],
        details={"destination": user.phone_masked, "target_type": resource_type},
    )
    await session.commit()
    await session.refresh(challenge)
    return challenge


async def verify_operation_auth_challenge(
    session: AsyncSession,
    user_id: str,
    challenge_id: str,
    code: str,
) -> OperationAuthChallenge:
    state_row = await assert_not_locked(session, user_id)
    challenge = await session.scalar(
        select(OperationAuthChallenge)
        .where(
            OperationAuthChallenge.id == challenge_id,
            OperationAuthChallenge.user_id == user_id,
        )
        .with_for_update()
    )
    if challenge is None:
        raise domain_error(
            status.HTTP_404_NOT_FOUND,
            "AUTH_CHALLENGE_NOT_FOUND",
            "验证挑战不存在。",
        )
    if challenge.status == "verified":
        return challenge
    if challenge.status != "pending":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "AUTH_CHALLENGE_NOT_ACTIVE",
            "验证挑战已失效。",
        )

    now = datetime.now(UTC)
    if aware_utc(challenge.expires_at) <= now:
        challenge.status = "expired"
        await session.commit()
        raise domain_error(
            status.HTTP_410_GONE,
            "AUTH_CHALLENGE_EXPIRED",
            "验证码已过期。",
        )

    supplied_digest = challenge_digest(challenge.id, code)
    if not hmac.compare_digest(supplied_digest, challenge.code_digest):
        challenge.attempts += 1
        state_row.consecutive_failures += 1
        state_row.last_failure_at = now
        is_locked = state_row.consecutive_failures >= settings.auth_max_failures
        if is_locked:
            state_row.locked_until = now + timedelta(minutes=settings.auth_lock_minutes)
            challenge.status = "locked"
        await append_audit_event(
            session,
            user_id=user_id,
            action="auth.operation.verify",
            outcome="failed",
            risk_level="red",
            resource_type="operation_auth_challenge",
            resource_id=challenge.id,
            reason_codes=["AUTH_FAILED", *(["SECURITY_FUSE_OPEN"] if is_locked else [])],
            details={"attempt": challenge.attempts},
        )
        await session.commit()
        if is_locked:
            raise domain_error(
                status.HTTP_423_LOCKED,
                "SECURITY_FUSE_OPEN",
                "连续验证失败，账户已临时锁定。",
            )
        raise domain_error(status.HTTP_401_UNAUTHORIZED, "INVALID_AUTH_CODE", "验证码错误。")

    challenge.status = "verified"
    challenge.verified_at = now
    state_row.consecutive_failures = 0
    state_row.last_failure_at = None
    state_row.locked_until = None
    await append_audit_event(
        session,
        user_id=user_id,
        action="auth.operation.verify",
        outcome="allowed",
        risk_level="red",
        resource_type="operation_auth_challenge",
        resource_id=challenge.id,
        reason_codes=["STRONG_AUTH_VERIFIED", challenge.action.upper()],
    )
    await session.commit()
    return challenge


async def execute_transfer(
    session: AsyncSession,
    user_id: str,
    draft_id: str,
    idempotency_key: str,
) -> TransferExecution:
    existing = await session.scalar(
        select(TransferExecution).where(
            TransferExecution.user_id == user_id,
            TransferExecution.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.draft_id != draft_id:
            raise domain_error(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "该幂等键已用于另一笔操作。",
            )
        return existing

    await assert_not_locked(session, user_id)
    draft = await owned_draft(session, user_id, draft_id, lock=True)
    decision = await session.scalar(
        select(PolicyDecision).where(PolicyDecision.draft_id == draft.id)
    )
    if decision is None or draft.status != "approved":
        await append_audit_event(
            session,
            user_id=user_id,
            action="transfer.execute",
            outcome="denied",
            resource_type="transfer_draft",
            resource_id=draft.id,
            reason_codes=["AUTHORIZATION_INCOMPLETE"],
        )
        await session.commit()
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "AUTHORIZATION_INCOMPLETE",
            "必须先完成策略判定和对应验证。",
        )

    now = datetime.now(UTC)
    if aware_utc(draft.expires_at) <= now:
        draft.status = "expired"
        await session.commit()
        raise domain_error(status.HTTP_410_GONE, "DRAFT_EXPIRED", "转账草案已过期。")
    if draft.scheduled_for is not None and aware_utc(draft.scheduled_for) > now:
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "SCHEDULE_NOT_DUE",
            "定时转账尚未到执行时间。",
        )

    account = await session.scalar(
        select(Account)
        .where(Account.id == draft.source_account_id, Account.user_id == user_id)
        .with_for_update()
    )
    payee = await session.scalar(
        select(Payee).where(
            Payee.id == draft.payee_id, Payee.owner_user_id == user_id
        )
    )
    if account is None or payee is None:
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "EXECUTION_RESOURCE_MISSING",
            "执行所需账户或收款人不存在。",
        )
    if account.status != "active":
        raise domain_error(
            status.HTTP_409_CONFLICT, "ACCOUNT_NOT_ACTIVE", "账户当前不可转出。"
        )
    if account.balance < draft.amount:
        raise domain_error(
            status.HTTP_409_CONFLICT, "INSUFFICIENT_FUNDS", "账户余额不足。"
        )

    execution_id = str(uuid4())
    transaction_id = str(uuid4())
    receipt_no = f"BA-{now:%Y%m%d}-{execution_id[:8].upper()}"
    transaction = Transaction(
        id=transaction_id,
        account_id=account.id,
        direction="debit",
        category="transfer",
        amount=draft.amount,
        currency=draft.currency,
        merchant=None,
        counterparty_name=payee.name,
        description=f"转账给{payee.name}",
        status="completed",
        occurred_at=now,
        is_recurring=False,
        risk_flag=None,
        external_reference=receipt_no,
    )
    execution = TransferExecution(
        id=execution_id,
        user_id=user_id,
        draft_id=draft.id,
        transaction_id=transaction_id,
        idempotency_key=idempotency_key,
        receipt_no=receipt_no,
        amount=draft.amount,
        currency=draft.currency,
        status="succeeded",
    )
    account.balance = (account.balance - draft.amount).quantize(CENT)
    draft.status = "executed"
    session.add_all([transaction, execution])
    await append_audit_event(
        session,
        user_id=user_id,
        action="transfer.execute",
        outcome="allowed",
        risk_level=decision.risk_level,
        resource_type="transfer_execution",
        resource_id=execution.id,
        reason_codes=["POLICY_AUTHORIZED", "IDEMPOTENT_EXECUTION"],
        details={
            "amount": str(draft.amount),
            "source_account_id": account.id,
            "idempotency_key": idempotency_key,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        replay = await session.scalar(
            select(TransferExecution).where(
                TransferExecution.user_id == user_id,
                TransferExecution.idempotency_key == idempotency_key,
            )
        )
        if replay is not None and replay.draft_id == draft_id:
            return replay
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "EXECUTION_CONFLICT",
            "转账执行发生幂等冲突。",
        ) from None
    await session.refresh(execution)
    return execution
