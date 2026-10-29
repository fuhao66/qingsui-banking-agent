from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Account,
    BankCard,
    BusinessOperation,
    InvestmentProduct,
    LifeEvent,
    Payee,
    Subscription,
    Transaction,
)
from app.services.audit import append_audit_event
from app.services.banking import CENT, domain_error, list_user_accounts, summarize_month


async def summarize_year(session: AsyncSession, user_id: str, year: int) -> dict[str, object]:
    months = [await summarize_month(session, user_id, f"{year}-{month:02d}") for month in range(1, 13)]
    income = sum((item.income for item in months), Decimal(0))
    outflow = sum((item.outflow for item in months), Decimal(0))
    categories: dict[str, Decimal] = {}
    suspicious = 0
    for item in months:
        suspicious += item.suspicious_count
        for category in item.categories:
            categories[category.category] = categories.get(category.category, Decimal(0)) + category.amount
    return {
        "year": year,
        "currency": "CNY",
        "income": str(income.quantize(CENT)),
        "outflow": str(outflow.quantize(CENT)),
        "net_cashflow": str((income - outflow).quantize(CENT)),
        "suspicious_count": suspicious,
        "months": [{"month": m.month, "income": str(m.income), "outflow": str(m.outflow)} for m in months],
        "categories": [
            {"category": key, "amount": str(value.quantize(CENT))}
            for key, value in sorted(categories.items(), key=lambda item: item[1], reverse=True)
        ],
    }


async def list_operations(session: AsyncSession, user_id: str, operation_type: str | None = None) -> list[BusinessOperation]:
    query = select(BusinessOperation).where(BusinessOperation.user_id == user_id)
    if operation_type:
        query = query.where(BusinessOperation.operation_type == operation_type)
    return list(await session.scalars(query.order_by(BusinessOperation.created_at.desc())))


async def _account(session: AsyncSession, user_id: str) -> Account:
    accounts = await list_user_accounts(session, user_id)
    account = next((item for item in accounts if item.status == "active" and item.currency == "CNY"), None)
    if not account:
        raise domain_error(status.HTTP_409_CONFLICT, "NO_ACTIVE_ACCOUNT", "没有可用的人民币付款账户。")
    return account


async def _record(
    session: AsyncSession, *, user_id: str, run_id: str | None, operation_type: str,
    status_value: str, risk_level: str, payload: dict[str, object], result: dict[str, object],
    scheduled_for: datetime | None = None,
) -> BusinessOperation:
    row = BusinessOperation(
        id=str(uuid4()), user_id=user_id, run_id=run_id, operation_type=operation_type,
        status=status_value, risk_level=risk_level, payload=payload, result=result,
        scheduled_for=scheduled_for,
    )
    session.add(row)
    await append_audit_event(
        session, user_id=user_id, action=operation_type, outcome="allowed",
        risk_level=risk_level, resource_type="business_operation", resource_id=row.id,
        reason_codes=["WHITELIST_EXECUTOR", "USER_AUTHORIZED"], details=result,
    )
    await session.commit()
    await session.refresh(row)
    return row


async def execute_operation(
    session: AsyncSession, user_id: str, run_id: str, operation_type: str,
    slots: dict[str, object],
) -> dict[str, object]:
    now = datetime.now(UTC)
    account = await _account(session, user_id)
    risk = "red" if operation_type.startswith(("investment.", "card.")) else "yellow"

    if operation_type == "transfer.schedule":
        amount = Decimal(str(slots["amount"])).quantize(CENT)
        query = str(slots.get("recipient_query") or "")
        payee = await session.scalar(select(Payee).where(Payee.owner_user_id == user_id, or_(Payee.name.ilike(f"%{query}%"), Payee.phone_last4 == query[-4:])))
        if not payee:
            raise domain_error(status.HTTP_404_NOT_FOUND, "PAYEE_NOT_FOUND", "未找到该姓名或手机号对应的收款人。")
        execute_at = datetime.fromisoformat(str(slots["scheduled_for"]))
        if execute_at <= now:
            raise domain_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "INVALID_SCHEDULE", "执行时间必须晚于当前时间。")
        if amount > account.balance:
            raise domain_error(status.HTTP_409_CONFLICT, "INSUFFICIENT_FUNDS", "账户余额不足。")
        result = {"recipient": payee.name, "amount": str(amount), "execute_at": execute_at.isoformat(), "status": "scheduled"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type=operation_type, status_value="scheduled", risk_level=risk, payload=slots, result=result, scheduled_for=execute_at)
    elif operation_type == "collection.aa":
        total = Decimal(str(slots["amount"])).quantize(CENT)
        count = int(str(slots["participant_count"]))
        result = {"title": str(slots.get("title") or "AA 收款"), "total_amount": str(total), "participant_count": count, "per_person": str((total / count).quantize(CENT)), "status": "collecting"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type=operation_type, status_value="collecting", risk_level=risk, payload=slots, result=result)
    elif operation_type == "investment.subscribe":
        amount = Decimal(str(slots["amount"])).quantize(CENT)
        query = str(slots.get("product_query") or "")
        product = await session.scalar(select(InvestmentProduct).where(InvestmentProduct.status == "active", InvestmentProduct.name.ilike(f"%{query}%")))
        if not product:
            raise domain_error(status.HTTP_404_NOT_FOUND, "PRODUCT_NOT_FOUND", "未找到该理财产品。")
        if amount < product.min_amount or amount > account.balance:
            raise domain_error(status.HTTP_409_CONFLICT, "INVESTMENT_AMOUNT_INVALID", "申购金额低于起购金额或账户余额不足。")
        account.balance = (account.balance - amount).quantize(CENT)
        receipt = f"INV-{now:%Y%m%d}-{uuid4().hex[:8].upper()}"
        session.add(Transaction(id=str(uuid4()), account_id=account.id, direction="debit", category="investment", amount=amount, currency="CNY", merchant=product.name, counterparty_name=None, description=f"申购{product.name}", status="completed", occurred_at=now, is_recurring=False, risk_flag=None, external_reference=receipt))
        result = {"product_id": product.id, "product_name": product.name, "principal": str(amount), "current_value": str(amount), "receipt_no": receipt, "status": "active"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type="investment.holding", status_value="active", risk_level=risk, payload=slots, result=result)
    elif operation_type == "investment.redeem":
        query = str(slots.get("product_query") or "")
        holding = await session.scalar(select(BusinessOperation).where(BusinessOperation.user_id == user_id, BusinessOperation.operation_type == "investment.holding", BusinessOperation.status == "active").order_by(BusinessOperation.created_at.desc()))
        if not holding or (query and query not in str(holding.result.get("product_name", ""))):
            raise domain_error(status.HTTP_404_NOT_FOUND, "HOLDING_NOT_FOUND", "未找到可赎回的对应持仓。")
        value = Decimal(str(holding.result["current_value"])).quantize(CENT)
        account.balance = (account.balance + value).quantize(CENT)
        holding.status = "redeemed"
        result = {"product_name": holding.result["product_name"], "redeemed_amount": str(value), "status": "redeemed"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type=operation_type, status_value="completed", risk_level=risk, payload=slots, result=result)
    elif operation_type == "card.apply":
        suffix = f"{int(uuid4().hex[-8:], 16) % 10000:04d}"
        card = BankCard(id=str(uuid4()), user_id=user_id, account_id=account.id, card_name=str(slots.get("card_type") or "AI 智能虚拟卡"), network="UnionPay", masked_number=f"**** **** **** {suffix}", last4=suffix, status="active", daily_limit=Decimal("3000.00"), transaction_limit=Decimal("1000.00"), online_transactions_enabled=True)
        session.add(card)
        result = {"card_id": card.id, "card_name": card.card_name, "masked_number": card.masked_number, "status": "approved"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type=operation_type, status_value="completed", risk_level=risk, payload=slots, result=result)
    elif operation_type in {"card.limit", "card.restriction"}:
        last4 = str(slots["card_last4"])
        card = await session.scalar(select(BankCard).where(BankCard.user_id == user_id, BankCard.last4 == last4).with_for_update())
        if not card:
            raise domain_error(status.HTTP_404_NOT_FOUND, "CARD_NOT_FOUND", "未找到指定尾号的银行卡。")
        if operation_type == "card.limit":
            card.transaction_limit = Decimal(str(slots["limit_amount"])).quantize(CENT)
            result = {"card": card.masked_number, "transaction_limit": str(card.transaction_limit), "status": "updated"}
        else:
            enabled = str(slots["online_enabled"]).lower() == "true"
            card.online_transactions_enabled = enabled
            result = {"card": card.masked_number, "online_transactions_enabled": enabled, "status": "updated"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type=operation_type, status_value="completed", risk_level=risk, payload=slots, result=result)
    elif operation_type == "subscription.reminder":
        query = str(slots.get("subscription_query") or "")
        sub = await session.scalar(select(Subscription).where(Subscription.user_id == user_id, Subscription.status == "active", or_(Subscription.merchant.ilike(f"%{query}%"), Subscription.product_name.ilike(f"%{query}%"))))
        if not sub:
            raise domain_error(status.HTTP_404_NOT_FOUND, "SUBSCRIPTION_NOT_FOUND", "未找到对应订阅。")
        lead = int(str(slots.get("lead_days") or "2"))
        result = {"merchant": sub.merchant, "next_charge_at": sub.next_charge_at.isoformat() if sub.next_charge_at else None, "lead_days": lead, "status": "scheduled"}
        row = await _record(session, user_id=user_id, run_id=run_id, operation_type=operation_type, status_value="scheduled", risk_level=risk, payload=slots, result=result, scheduled_for=sub.next_charge_at)
    else:
        raise domain_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "OPERATION_NOT_WHITELISTED", "该操作不在业务白名单中。")
    return {"operation_id": row.id, "operation_type": row.operation_type, **row.result}


async def list_holdings(session: AsyncSession, user_id: str) -> list[dict[str, object]]:
    rows = await session.scalars(select(BusinessOperation).where(BusinessOperation.user_id == user_id, BusinessOperation.operation_type == "investment.holding", BusinessOperation.status == "active").order_by(BusinessOperation.created_at.desc()))
    return [{"holding_id": row.id, **row.result} for row in rows]


async def scan_life_events(session: AsyncSession, user_id: str) -> list[dict[str, object]]:
    rows = await session.scalars(select(LifeEvent).where(LifeEvent.user_id == user_id, LifeEvent.enabled.is_(True)).order_by(LifeEvent.event_date))
    return [{"event_id": row.id, "person": row.person, "event_type": row.event_type, "event_date": row.event_date.isoformat(), "default_budget": str(row.default_budget)} for row in rows]
