from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_demo_user_id
from app.db.models import PolicyDecision
from app.domain.schemas import (
    AuditEventListResponse,
    AuditEventResponse,
    AuthChallengeResponse,
    AuthVerificationRequest,
    AuthVerificationResponse,
    PolicyDecisionResponse,
    PolicyEvaluationResponse,
    PolicyMatrixItem,
    PolicyMatrixResponse,
    SecurityStatusResponse,
    TransferConfirmationRequest,
    TransferConfirmationResponse,
    TransferExecutionResponse,
)
from app.services import security as security_service
from app.services.audit import list_audit_events, verify_audit_chain
from app.services.banking import domain_error

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
DemoUserId = Annotated[str, Depends(get_demo_user_id)]


@router.get(
    "/security/policy-matrix",
    response_model=PolicyMatrixResponse,
    tags=["security"],
)
async def policy_matrix() -> PolicyMatrixResponse:
    return PolicyMatrixResponse(
        policy_version=security_service.POLICY_VERSION,
        transfer_daily_threshold=security_service.TRANSFER_DAILY_THRESHOLD,
        levels=[
            PolicyMatrixItem(
                risk_level="green",
                execution_strategy="automatic",
                examples=["余额查询", "交易记录查询", "账单分析"],
            ),
            PolicyMatrixItem(
                risk_level="yellow",
                execution_strategy="explicit_confirmation",
                examples=["日累计不超过 1000 元的小额转账", "取消订阅"],
            ),
            PolicyMatrixItem(
                risk_level="red",
                execution_strategy="strong_authentication",
                examples=["日累计超过 1000 元的转账", "理财申购", "卡片挂失"],
            ),
        ],
    )


@router.get(
    "/security/status", response_model=SecurityStatusResponse, tags=["security"]
)
async def security_status(
    session: DatabaseSession, user_id: DemoUserId
) -> SecurityStatusResponse:
    state_row = await security_service.get_security_state(session, user_id)
    locked_until = state_row.locked_until
    locked = (
        locked_until is not None
        and security_service.aware_utc(locked_until) > datetime.now(UTC)
    )
    return SecurityStatusResponse(
        locked=locked,
        consecutive_failures=state_row.consecutive_failures,
        locked_until=locked_until,
        policy_version=security_service.POLICY_VERSION,
    )


@router.get(
    "/security/audit-events",
    response_model=AuditEventListResponse,
    tags=["security"],
)
async def audit_events(
    session: DatabaseSession,
    user_id: DemoUserId,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AuditEventListResponse:
    rows = await list_audit_events(session, user_id, limit)
    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(row) for row in rows],
        total=len(rows),
        chain_valid=verify_audit_chain(rows),
    )


@router.post(
    "/transfer-drafts/{draft_id}/prepare",
    response_model=PolicyEvaluationResponse,
    tags=["transfer-security"],
)
async def prepare_transfer(
    draft_id: str, session: DatabaseSession, user_id: DemoUserId
) -> PolicyEvaluationResponse:
    draft, decision = await security_service.evaluate_transfer_policy(
        session, user_id, draft_id
    )
    return PolicyEvaluationResponse(
        draft_id=draft.id,
        draft_status=draft.status,
        decision=PolicyDecisionResponse.model_validate(decision),
        next_action=security_service.next_action_for_status(draft.status),
    )


@router.get(
    "/transfer-drafts/{draft_id}/policy-decision",
    response_model=PolicyDecisionResponse,
    tags=["transfer-security"],
)
async def transfer_policy_decision(
    draft_id: str, session: DatabaseSession, user_id: DemoUserId
) -> PolicyDecisionResponse:
    await security_service.owned_draft(session, user_id, draft_id)
    decision = await session.scalar(
        select(PolicyDecision).where(PolicyDecision.draft_id == draft_id)
    )
    if decision is None:
        raise domain_error(
            status.HTTP_404_NOT_FOUND,
            "POLICY_DECISION_NOT_FOUND",
            "该转账尚未完成策略判定。",
        )
    return PolicyDecisionResponse.model_validate(decision)


@router.post(
    "/transfer-drafts/{draft_id}/confirm",
    response_model=TransferConfirmationResponse,
    tags=["transfer-security"],
)
async def confirm_transfer(
    draft_id: str,
    payload: TransferConfirmationRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> TransferConfirmationResponse:
    draft = await security_service.confirm_transfer(
        session, user_id, draft_id, payload.confirmed
    )
    return TransferConfirmationResponse(
        draft_id=draft.id,
        status=draft.status,
        next_action=security_service.next_action_for_status(draft.status),
    )


@router.post(
    "/transfer-drafts/{draft_id}/auth-challenges",
    response_model=AuthChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["transfer-security"],
)
async def create_auth_challenge(
    draft_id: str, session: DatabaseSession, user_id: DemoUserId
) -> AuthChallengeResponse:
    challenge = await security_service.create_auth_challenge(
        session, user_id, draft_id
    )
    return AuthChallengeResponse.model_validate(challenge)


@router.post(
    "/auth-challenges/{challenge_id}/verify",
    response_model=AuthVerificationResponse,
    tags=["transfer-security"],
)
async def verify_auth_challenge(
    challenge_id: str,
    payload: AuthVerificationRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AuthVerificationResponse:
    challenge, draft = await security_service.verify_auth_challenge(
        session, user_id, challenge_id, payload.code
    )
    return AuthVerificationResponse(
        challenge_id=challenge.id,
        draft_id=draft.id,
        challenge_status=challenge.status,
        draft_status=draft.status,
        next_action=security_service.next_action_for_status(draft.status),
    )


@router.post(
    "/transfer-drafts/{draft_id}/execute",
    response_model=TransferExecutionResponse,
    tags=["transfer-security"],
)
async def execute_transfer(
    draft_id: str,
    session: DatabaseSession,
    user_id: DemoUserId,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=80)
    ],
) -> TransferExecutionResponse:
    execution = await security_service.execute_transfer(
        session, user_id, draft_id, idempotency_key
    )
    return TransferExecutionResponse.model_validate(execution)
