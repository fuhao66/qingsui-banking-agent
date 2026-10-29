from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_demo_user_id
from app.domain.schemas import (
    AccountListResponse,
    AccountResponse,
    BankCardListResponse,
    BankCardResponse,
    InvestmentProductListResponse,
    InvestmentProductResponse,
    PayeeSearchResponse,
    SubscriptionListResponse,
    TransactionListResponse,
    TransferDraftCreate,
    TransferDraftResponse,
    UserProfileResponse,
)
from app.services import banking as banking_service
from app.services import extended_banking as extended_service
from app.services import security as security_service

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
DemoUserId = Annotated[str, Depends(get_demo_user_id)]


@router.get("/users/me", response_model=UserProfileResponse, tags=["users"])
async def profile(session: DatabaseSession, user_id: DemoUserId) -> UserProfileResponse:
    return UserProfileResponse.model_validate(await banking_service.get_user(session, user_id))


@router.get("/accounts", response_model=AccountListResponse, tags=["accounts"])
async def accounts(session: DatabaseSession, user_id: DemoUserId) -> AccountListResponse:
    rows = await banking_service.list_user_accounts(session, user_id)
    total_balance = sum((row.balance for row in rows if row.currency == "CNY"), Decimal(0))
    return AccountListResponse(
        items=[AccountResponse.model_validate(row) for row in rows],
        total=len(rows),
        total_balance=total_balance,
        currency="CNY",
    )


@router.get("/accounts/{account_id}", response_model=AccountResponse, tags=["accounts"])
async def account(
    account_id: str, session: DatabaseSession, user_id: DemoUserId
) -> AccountResponse:
    row = await banking_service.get_owned_account(session, user_id, account_id)
    return AccountResponse.model_validate(row)


@router.get("/transactions", response_model=TransactionListResponse, tags=["transactions"])
async def transactions(
    session: DatabaseSession,
    user_id: DemoUserId,
    account_id: str | None = None,
    category: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionListResponse:
    rows, total = await banking_service.list_user_transactions(
        session,
        user_id,
        account_id=account_id,
        category=category,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    return TransactionListResponse(items=rows, total=total, limit=limit, offset=offset)


@router.get("/bill-summary", tags=["transactions"])
async def bill_summary(
    session: DatabaseSession,
    user_id: DemoUserId,
    month: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")] = "2026-08",
):
    return await banking_service.summarize_month(session, user_id, month)


@router.get("/annual-report", tags=["transactions"])
async def annual_report(
    session: DatabaseSession,
    user_id: DemoUserId,
    year: Annotated[int, Query(ge=2020, le=2100)] = 2026,
):
    return await extended_service.summarize_year(session, user_id, year)


@router.get("/investment-holdings", tags=["investments"])
async def investment_holdings(session: DatabaseSession, user_id: DemoUserId):
    items = await extended_service.list_holdings(session, user_id)
    return {"items": items, "total": len(items)}


@router.get("/business-operations", tags=["operations"])
async def business_operations(
    session: DatabaseSession, user_id: DemoUserId, operation_type: str | None = None
):
    rows = await extended_service.list_operations(session, user_id, operation_type)
    return {"items": [
        {"id": row.id, "operation_type": row.operation_type, "status": row.status,
         "risk_level": row.risk_level, "payload": row.payload, "result": row.result,
         "scheduled_for": row.scheduled_for, "created_at": row.created_at}
        for row in rows
    ], "total": len(rows)}


@router.get("/life-events", tags=["life-events"])
async def life_events(session: DatabaseSession, user_id: DemoUserId):
    items = await extended_service.scan_life_events(session, user_id)
    return {"items": items, "total": len(items)}


@router.get("/payees/search", response_model=PayeeSearchResponse, tags=["payees"])
async def search_payees(
    session: DatabaseSession,
    user_id: DemoUserId,
    q: Annotated[str, Query(min_length=1, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> PayeeSearchResponse:
    rows = await banking_service.search_user_payees(session, user_id, q, limit)
    return PayeeSearchResponse(
        query=q,
        items=rows,
        requires_disambiguation=len(rows) > 1,
    )


@router.get("/subscriptions", response_model=SubscriptionListResponse, tags=["subscriptions"])
async def subscriptions(
    session: DatabaseSession,
    user_id: DemoUserId,
    subscription_status: Annotated[
        str | None, Query(alias="status", pattern=r"^(active|paused|cancelled)$")
    ] = "active",
) -> SubscriptionListResponse:
    rows = await banking_service.list_user_subscriptions(
        session, user_id, subscription_status
    )
    monthly_equivalent = sum(
        (
            row.amount if row.billing_cycle == "monthly" else row.amount / Decimal(12)
            for row in rows
            if row.status == "active"
        ),
        Decimal(0),
    )
    return SubscriptionListResponse(
        items=rows,
        total=len(rows),
        monthly_equivalent=monthly_equivalent.quantize(Decimal("0.01")),
    )


@router.get("/cards", response_model=BankCardListResponse, tags=["cards"])
async def cards(session: DatabaseSession, user_id: DemoUserId) -> BankCardListResponse:
    rows = await banking_service.list_user_cards(session, user_id)
    return BankCardListResponse(
        items=[BankCardResponse.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.get(
    "/investment-products",
    response_model=InvestmentProductListResponse,
    tags=["investments"],
)
async def investment_products(session: DatabaseSession) -> InvestmentProductListResponse:
    rows = await banking_service.list_investment_products(session)
    return InvestmentProductListResponse(
        items=[InvestmentProductResponse.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.post(
    "/transfer-drafts",
    response_model=TransferDraftResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["transfer-drafts"],
)
async def create_transfer_draft(
    payload: TransferDraftCreate,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> TransferDraftResponse:
    await security_service.assert_not_locked(session, user_id)
    row = await banking_service.create_transfer_draft(session, user_id, payload)
    return TransferDraftResponse.model_validate(row)


@router.get(
    "/transfer-drafts/{draft_id}",
    response_model=TransferDraftResponse,
    tags=["transfer-drafts"],
)
async def transfer_draft(
    draft_id: str, session: DatabaseSession, user_id: DemoUserId
) -> TransferDraftResponse:
    row = await banking_service.get_transfer_draft(session, user_id, draft_id)
    return TransferDraftResponse.model_validate(row)
