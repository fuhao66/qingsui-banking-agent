import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Account,
    BankCard,
    ExperienceSession,
    LifeEvent,
    Payee,
    SecurityState,
    Subscription,
    Transaction,
    User,
)
from app.domain.constants import DEMO_USER_ID


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def auth_error(code: str, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def clone_demo_sandbox(
    session: AsyncSession, display_name: str
) -> User:
    template = await session.get(User, DEMO_USER_ID)
    if template is None:
        raise auth_error(
            "DEMO_TEMPLATE_MISSING",
            "演示模板尚未初始化。",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    user_id = str(uuid4())
    user = User(
        id=user_id,
        display_name=display_name,
        phone_masked="体验用户",
        customer_no=f"EXP-{user_id[:8].upper()}",
        risk_profile=template.risk_profile,
    )
    session.add(user)
    await session.flush()
    session.add(SecurityState(user_id=user_id, consecutive_failures=0))

    source_accounts = list(
        await session.scalars(select(Account).where(Account.user_id == DEMO_USER_ID))
    )
    account_ids: dict[str, str] = {}
    for source in source_accounts:
        new_id = str(uuid4())
        account_ids[source.id] = new_id
        session.add(
            Account(
                id=new_id,
                user_id=user_id,
                name=source.name,
                account_type=source.account_type,
                masked_number=source.masked_number,
                currency=source.currency,
                balance=source.balance,
                status="active",
            )
        )
    await session.flush()

    payees = await session.scalars(select(Payee).where(Payee.owner_user_id == DEMO_USER_ID))
    for source in payees:
        session.add(
            Payee(
                id=str(uuid4()),
                owner_user_id=user_id,
                name=source.name,
                alias=source.alias,
                bank_name=source.bank_name,
                account_masked=source.account_masked,
                account_token=f"experience-{user_id[:8]}-{source.phone_last4}",
                phone_masked=source.phone_masked,
                phone_last4=source.phone_last4,
                is_frequent=source.is_frequent,
                last_transfer_at=source.last_transfer_at,
            )
        )

    subscriptions = await session.scalars(
        select(Subscription).where(Subscription.user_id == DEMO_USER_ID)
    )
    for source in subscriptions:
        session.add(
            Subscription(
                id=str(uuid4()),
                user_id=user_id,
                account_id=account_ids[source.account_id],
                merchant=source.merchant,
                product_name=source.product_name,
                amount=source.amount,
                currency=source.currency,
                billing_cycle=source.billing_cycle,
                status="active",
                next_charge_at=source.next_charge_at,
                last_charge_at=source.last_charge_at,
                cancellation_channel=source.cancellation_channel,
                confidence=source.confidence,
            )
        )

    cards = await session.scalars(select(BankCard).where(BankCard.user_id == DEMO_USER_ID))
    for source in cards:
        session.add(
            BankCard(
                id=str(uuid4()),
                user_id=user_id,
                account_id=account_ids[source.account_id],
                card_name=source.card_name,
                network=source.network,
                masked_number=source.masked_number,
                last4=source.last4,
                status="active",
                daily_limit=source.daily_limit,
                transaction_limit=source.transaction_limit,
                online_transactions_enabled=source.online_transactions_enabled,
            )
        )

    events = await session.scalars(select(LifeEvent).where(LifeEvent.user_id == DEMO_USER_ID))
    for source in events:
        session.add(
            LifeEvent(
                id=str(uuid4()), user_id=user_id, person=source.person,
                event_type=source.event_type, event_date=source.event_date,
                default_budget=source.default_budget, enabled=source.enabled,
            )
        )

    source_account_ids = list(account_ids)
    transactions = await session.scalars(
        select(Transaction).where(Transaction.account_id.in_(source_account_ids))
    )
    for source in transactions:
        transaction_id = str(uuid4())
        session.add(
            Transaction(
                id=transaction_id,
                account_id=account_ids[source.account_id],
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
                external_reference=f"EXP-{user_id[:8]}-{transaction_id[:12]}",
            )
        )
    await session.flush()
    return user


async def create_experience_session(
    session: AsyncSession, invite_code: str, display_name: str
) -> tuple[str, ExperienceSession, User]:
    if not settings.public_invite_code or not hmac.compare_digest(
        invite_code, settings.public_invite_code
    ):
        raise auth_error("INVALID_INVITE_CODE", "体验邀请码无效。", status.HTTP_403_FORBIDDEN)
    now = datetime.now(UTC)
    active = await session.scalar(
        select(func.count())
        .select_from(ExperienceSession)
        .where(ExperienceSession.revoked.is_(False), ExperienceSession.expires_at > now)
    )
    if int(active or 0) >= settings.experience_max_active_sessions:
        raise auth_error(
            "EXPERIENCE_CAPACITY_REACHED",
            "当前体验人数已满，请稍后再试。",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    user = await clone_demo_sandbox(session, display_name)
    raw_token = secrets.token_urlsafe(32)
    experience = ExperienceSession(
        id=str(uuid4()),
        user_id=user.id,
        token_digest=token_digest(raw_token),
        display_name=display_name,
        request_count=0,
        request_window_count=0,
        revoked=False,
        last_seen_at=now,
        request_window_started_at=now,
        expires_at=now + timedelta(hours=settings.experience_session_hours),
    )
    session.add(experience)
    await session.commit()
    return raw_token, experience, user


async def authenticate_token(session: AsyncSession, token: str) -> ExperienceSession:
    experience = await session.scalar(
        select(ExperienceSession).where(ExperienceSession.token_digest == token_digest(token))
    )
    now = datetime.now(UTC)
    if experience is None or experience.revoked:
        raise auth_error("INVALID_EXPERIENCE_TOKEN", "体验会话无效，请重新登录。")
    if aware_utc(experience.expires_at) <= now:
        raise auth_error("EXPERIENCE_TOKEN_EXPIRED", "体验会话已过期，请重新登录。")
    window_started = aware_utc(experience.request_window_started_at)
    if (now - window_started).total_seconds() >= 60:
        experience.request_window_started_at = now
        experience.request_window_count = 0
    experience.request_window_count += 1
    experience.request_count += 1
    experience.last_seen_at = now
    await session.commit()
    if experience.request_window_count > settings.experience_requests_per_minute:
        raise auth_error(
            "EXPERIENCE_RATE_LIMITED",
            "请求过于频繁，请稍后再试。",
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
    return experience


async def revoke_session(session: AsyncSession, experience: ExperienceSession) -> None:
    experience.revoked = True
    await session.commit()
