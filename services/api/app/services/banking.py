from calendar import monthrange
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Account,
    BankCard,
    InvestmentProduct,
    Payee,
    Subscription,
    Transaction,
    TransferDraft,
    User,
)
from app.domain.schemas import BillSummaryResponse, CategorySummary, TransferDraftCreate
from app.services.audit import append_audit_event

CENT = Decimal("0.01")


def domain_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def get_user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise domain_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "未找到当前演示用户。")
    return user


async def list_user_accounts(session: AsyncSession, user_id: str) -> list[Account]:
    rows = await session.scalars(
        select(Account).where(Account.user_id == user_id).order_by(Account.created_at)
    )
    return list(rows)


async def get_owned_account(session: AsyncSession, user_id: str, account_id: str) -> Account:
    account = await session.scalar(
        select(Account).where(Account.id == account_id, Account.user_id == user_id)
    )
    if account is None:
        raise domain_error(status.HTTP_404_NOT_FOUND, "ACCOUNT_NOT_FOUND", "账户不存在或无权访问。")
    return account


async def list_user_transactions(
    session: AsyncSession,
    user_id: str,
    *,
    account_id: str | None,
    category: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[Transaction], int]:
    filters = [Account.user_id == user_id]
    if account_id:
        filters.append(Transaction.account_id == account_id)
    if category:
        filters.append(Transaction.category == category)
    if start_at:
        filters.append(Transaction.occurred_at >= start_at)
    if end_at:
        filters.append(Transaction.occurred_at < end_at)

    base = select(Transaction).join(Account, Account.id == Transaction.account_id).where(*filters)
    total = await session.scalar(
        select(func.count()).select_from(base.order_by(None).subquery())
    )
    rows = await session.scalars(
        base.order_by(Transaction.occurred_at.desc()).limit(limit).offset(offset)
    )
    return list(rows), int(total or 0)


def parse_month(month: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError as exc:
        raise domain_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_MONTH",
            "月份必须使用 YYYY-MM 格式。",
        ) from exc
    last_day = monthrange(start.year, start.month)[1]
    end = start.replace(day=last_day) + timedelta(days=1)
    return start, end


async def summarize_month(
    session: AsyncSession, user_id: str, month: str
) -> BillSummaryResponse:
    start, end = parse_month(month)
    previous_end = start
    previous_year, previous_month = (
        (start.year - 1, 12) if start.month == 1 else (start.year, start.month - 1)
    )
    previous_start = datetime(previous_year, previous_month, 1, tzinfo=UTC)

    async def period_rows(period_start: datetime, period_end: datetime) -> list[Transaction]:
        result = await session.scalars(
            select(Transaction)
            .join(Account, Account.id == Transaction.account_id)
            .where(
                Account.user_id == user_id,
                Transaction.occurred_at >= period_start,
                Transaction.occurred_at < period_end,
                Transaction.status == "completed",
            )
        )
        return list(result)

    rows = await period_rows(start, end)
    previous_rows = await period_rows(previous_start, previous_end)
    income = sum((row.amount for row in rows if row.direction == "credit"), Decimal(0))
    outflow = sum((row.amount for row in rows if row.direction == "debit"), Decimal(0))
    previous_outflow = sum(
        (row.amount for row in previous_rows if row.direction == "debit"), Decimal(0)
    )

    category_amounts: dict[str, Decimal] = {}
    category_counts: dict[str, int] = {}
    for row in rows:
        if row.direction != "debit":
            continue
        category_amounts[row.category] = (
            category_amounts.get(row.category, Decimal(0)) + row.amount
        )
        category_counts[row.category] = category_counts.get(row.category, 0) + 1

    categories = [
        CategorySummary(
            category=category,
            amount=amount.quantize(CENT),
            transaction_count=category_counts[category],
            share_percent=(
                (amount / outflow * Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
                if outflow
                else Decimal(0)
            ),
        )
        for category, amount in sorted(category_amounts.items(), key=lambda item: item[1], reverse=True)
    ]
    change = None
    if previous_outflow:
        change = (
            (outflow - previous_outflow) / previous_outflow * Decimal(100)
        ).quantize(CENT, rounding=ROUND_HALF_UP)

    return BillSummaryResponse(
        month=month,
        currency="CNY",
        income=income.quantize(CENT),
        outflow=outflow.quantize(CENT),
        net_cashflow=(income - outflow).quantize(CENT),
        previous_month_outflow=previous_outflow.quantize(CENT),
        outflow_change_percent=change,
        transaction_count=len(rows),
        suspicious_count=sum(1 for row in rows if row.risk_flag),
        categories=categories,
    )


async def search_user_payees(
    session: AsyncSession, user_id: str, query: str, limit: int
) -> list[Payee]:
    normalized = query.strip()
    if not normalized:
        return []
    pattern = f"%{normalized}%"
    rows = await session.scalars(
        select(Payee)
        .where(
            Payee.owner_user_id == user_id,
            or_(
                Payee.name.ilike(pattern),
                Payee.alias.ilike(pattern),
                Payee.phone_last4 == normalized,
            ),
        )
        .order_by(Payee.is_frequent.desc(), Payee.last_transfer_at.desc())
        .limit(limit)
    )
    return list(rows)


async def list_user_subscriptions(
    session: AsyncSession, user_id: str, subscription_status: str | None
) -> list[Subscription]:
    query = select(Subscription).where(Subscription.user_id == user_id)
    if subscription_status:
        query = query.where(Subscription.status == subscription_status)
    rows = await session.scalars(query.order_by(Subscription.next_charge_at))
    return list(rows)


async def search_user_subscriptions(
    session: AsyncSession, user_id: str, query: str
) -> list[Subscription]:
    normalized = query.strip()
    if not normalized:
        return []
    pattern = f"%{normalized}%"
    rows = await session.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            or_(
                Subscription.merchant.ilike(pattern),
                Subscription.product_name.ilike(pattern),
            ),
        )
        .order_by(Subscription.next_charge_at)
    )
    return list(rows)


async def cancel_subscription(
    session: AsyncSession, user_id: str, subscription_id: str
) -> Subscription:
    subscription = await session.scalar(
        select(Subscription)
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user_id,
        )
        .with_for_update()
    )
    if subscription is None:
        raise domain_error(
            status.HTTP_404_NOT_FOUND,
            "SUBSCRIPTION_NOT_FOUND",
            "没有找到该订阅。",
        )
    if subscription.status == "cancelled":
        return subscription
    if subscription.status != "active":
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "SUBSCRIPTION_NOT_ACTIVE",
            "该订阅当前不可取消。",
        )
    subscription.status = "cancelled"
    await append_audit_event(
        session,
        user_id=user_id,
        action="subscription.cancel",
        outcome="allowed",
        risk_level="yellow",
        resource_type="subscription",
        resource_id=subscription.id,
        reason_codes=["USER_CONFIRMED", "SUBSCRIPTION_CANCELLED"],
        details={"merchant": subscription.merchant, "amount": str(subscription.amount)},
    )
    await session.commit()
    return subscription


async def list_user_cards(session: AsyncSession, user_id: str) -> list[BankCard]:
    rows = await session.scalars(
        select(BankCard).where(BankCard.user_id == user_id).order_by(BankCard.created_at)
    )
    return list(rows)


async def resolve_user_card(
    session: AsyncSession, user_id: str, *, last4: str | None, card_id: str | None = None
) -> BankCard | None:
    query = select(BankCard).where(BankCard.user_id == user_id)
    if card_id:
        query = query.where(BankCard.id == card_id)
    elif last4:
        query = query.where(BankCard.last4 == last4)
    else:
        return None
    return await session.scalar(query)


async def change_card_status(
    session: AsyncSession,
    user_id: str,
    card_id: str,
    action: str,
) -> BankCard:
    card = await session.scalar(
        select(BankCard)
        .where(BankCard.id == card_id, BankCard.user_id == user_id)
        .with_for_update()
    )
    if card is None:
        raise domain_error(status.HTTP_404_NOT_FOUND, "CARD_NOT_FOUND", "银行卡不存在。")
    target_status = {"lock": "locked", "unlock": "active", "report_lost": "lost"}.get(action)
    if target_status is None:
        raise domain_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_CARD_ACTION",
            "不支持该卡片操作。",
        )
    card.status = target_status
    await append_audit_event(
        session,
        user_id=user_id,
        action=f"card.{action}",
        outcome="allowed",
        risk_level="red",
        resource_type="bank_card",
        resource_id=card.id,
        reason_codes=["STRONG_AUTH_VERIFIED", "CARD_STATUS_CHANGED"],
        details={"last4": card.last4, "status": target_status},
    )
    await session.commit()
    return card


async def recommend_investments(
    session: AsyncSession,
    user_id: str,
    amount: Decimal,
    horizon_months: int,
    preference: str | None,
) -> tuple[list[InvestmentProduct], str]:
    user = await get_user(session, user_id)
    profile_cap = {"conservative": 1, "balanced": 2, "aggressive": 3}.get(
        user.risk_profile, 1
    )
    requested_cap = {"conservative": 1, "balanced": 2, "aggressive": 3}.get(
        preference or user.risk_profile, profile_cap
    )
    effective_cap = min(profile_cap, requested_cap)
    allowed_risks = [risk for risk, rank in {"low": 1, "medium": 2, "high": 3}.items() if rank <= effective_cap]
    rows = await session.scalars(
        select(InvestmentProduct)
        .where(
            InvestmentProduct.status == "active",
            InvestmentProduct.risk_level.in_(allowed_risks),
            InvestmentProduct.min_amount <= amount,
            InvestmentProduct.term_months <= horizon_months,
        )
        .order_by(
            InvestmentProduct.expected_return_high.desc(),
            InvestmentProduct.term_months,
        )
        .limit(3)
    )
    effective_profile = {1: "conservative", 2: "balanced", 3: "aggressive"}[effective_cap]
    return list(rows), effective_profile


async def list_investment_products(session: AsyncSession) -> list[InvestmentProduct]:
    rows = await session.scalars(
        select(InvestmentProduct)
        .where(InvestmentProduct.status == "active")
        .order_by(InvestmentProduct.risk_level, InvestmentProduct.term_months)
    )
    return list(rows)


async def create_transfer_draft(
    session: AsyncSession,
    user_id: str,
    payload: TransferDraftCreate,
) -> TransferDraft:
    account = await get_owned_account(session, user_id, payload.source_account_id)
    payee = await session.scalar(
        select(Payee).where(Payee.id == payload.payee_id, Payee.owner_user_id == user_id)
    )
    if payee is None:
        raise domain_error(status.HTTP_404_NOT_FOUND, "PAYEE_NOT_FOUND", "收款人不存在。")
    if account.status != "active":
        raise domain_error(status.HTTP_409_CONFLICT, "ACCOUNT_NOT_ACTIVE", "账户当前不可转出。")
    if payload.currency != account.currency:
        raise domain_error(
            status.HTTP_409_CONFLICT,
            "CURRENCY_MISMATCH",
            "转账币种与付款账户币种不一致。",
        )
    if payload.amount > account.balance:
        raise domain_error(status.HTTP_409_CONFLICT, "INSUFFICIENT_FUNDS", "账户余额不足。")

    now = datetime.now(UTC)
    if payload.scheduled_for is not None and payload.scheduled_for <= now:
        raise domain_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_SCHEDULE",
            "定时转账时间必须晚于当前时间。",
        )

    draft = TransferDraft(
        id=str(uuid4()),
        user_id=user_id,
        source_account_id=payload.source_account_id,
        payee_id=payload.payee_id,
        amount=payload.amount.quantize(CENT),
        currency=payload.currency,
        memo=payload.memo,
        scheduled_for=payload.scheduled_for,
        status="pending_policy",
        expires_at=now + timedelta(minutes=5),
    )
    session.add(draft)
    await append_audit_event(
        session,
        user_id=user_id,
        action="transfer.draft.create",
        outcome="recorded",
        resource_type="transfer_draft",
        resource_id=draft.id,
        reason_codes=["AWAITING_SERVER_POLICY"],
        details={
            "amount": str(draft.amount),
            "source_account_id": draft.source_account_id,
            "payee_id": draft.payee_id,
        },
    )
    await session.commit()
    await session.refresh(draft)
    return draft


async def get_transfer_draft(
    session: AsyncSession, user_id: str, draft_id: str
) -> TransferDraft:
    draft = await session.scalar(
        select(TransferDraft).where(
            TransferDraft.id == draft_id, TransferDraft.user_id == user_id
        )
    )
    if draft is None:
        raise domain_error(
            status.HTTP_404_NOT_FOUND, "TRANSFER_DRAFT_NOT_FOUND", "转账草案不存在。"
        )
    return draft
