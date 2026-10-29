from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runtime as agent_runtime
from app.agent.tools import TOOL_DEFINITIONS
from app.api.dependencies import get_db, get_demo_user_id
from app.db.models import AgentRun
from app.domain.schemas import (
    AgentConversationResponse,
    AgentEvidenceRunCreate,
    AgentHandoffRequest,
    AgentHumanResolutionRequest,
    AgentResumeRequest,
    AgentRunCreate,
    AgentRunResponse,
    AgentToolResponse,
)

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
DemoUserId = Annotated[str, Depends(get_demo_user_id)]


@router.get("/agent/tools", response_model=list[AgentToolResponse], tags=["agent"])
async def agent_tools() -> list[AgentToolResponse]:
    return [
        AgentToolResponse(
            name=tool.name,
            risk_level=tool.risk_level,
            side_effect=tool.side_effect,
            description=tool.description,
        )
        for tool in TOOL_DEFINITIONS
    ]


@router.post(
    "/agent/runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["agent"],
)
async def create_agent_run(
    payload: AgentRunCreate,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AgentRunResponse:
    run = await agent_runtime.create_run(
        session,
        user_id,
        payload.message,
        payload.channel,
        payload.conversation_id,
    )
    return await agent_runtime.present_run(session, run)


@router.post(
    "/agent/evidence-runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["agent", "guardian"],
)
async def create_evidence_run(
    payload: AgentEvidenceRunCreate,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AgentRunResponse:
    run = await agent_runtime.create_run(
        session, user_id, payload.message, payload.channel, payload.conversation_id,
        evidence_text=payload.evidence_text, image_data_url=payload.image_data_url,
    )
    return await agent_runtime.present_run(session, run)


@router.get("/agent/runs/{run_id}/decision-receipt", tags=["agent", "guardian"])
async def decision_receipt(
    run_id: str, session: DatabaseSession, user_id: DemoUserId
):
    run = await agent_runtime.owned_run(session, user_id, run_id)
    assessment = await agent_runtime.guardian_service.assessment_for_run(session, run.id)
    if assessment is None:
        raise agent_runtime.banking_service.domain_error(
            status.HTTP_404_NOT_FOUND, "DECISION_RECEIPT_NOT_FOUND", "决策回单不存在。"
        )
    return {"receipt": assessment.decision_receipt, "receipt_hash": assessment.receipt_hash}


@router.get(
    "/agent/runs/{run_id}", response_model=AgentRunResponse, tags=["agent"]
)
async def get_agent_run(
    run_id: str, session: DatabaseSession, user_id: DemoUserId
) -> AgentRunResponse:
    run = await agent_runtime.owned_run(session, user_id, run_id)
    return await agent_runtime.present_run(session, run)


@router.get("/agent/runs", response_model=list[AgentRunResponse], tags=["agent"])
async def list_agent_runs(
    session: DatabaseSession,
    user_id: DemoUserId,
    conversation_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[AgentRunResponse]:
    statement = select(AgentRun).where(AgentRun.user_id == user_id)
    if conversation_id:
        statement = statement.where(AgentRun.conversation_id == conversation_id)
    rows = await session.scalars(statement.order_by(AgentRun.created_at.desc()).limit(limit))
    return [await agent_runtime.present_run(session, run) for run in rows]


@router.post(
    "/agent/runs/{run_id}/resume",
    response_model=AgentRunResponse,
    tags=["agent"],
)
async def resume_agent_run(
    run_id: str,
    payload: AgentResumeRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AgentRunResponse:
    run = await agent_runtime.resume_run(session, user_id, run_id, payload)
    return await agent_runtime.present_run(session, run)


@router.post(
    "/agent/runs/{run_id}/handoff",
    response_model=AgentRunResponse,
    tags=["agent"],
)
async def handoff_agent_run(
    run_id: str,
    payload: AgentHandoffRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AgentRunResponse:
    run = await agent_runtime.owned_run(session, user_id, run_id, lock=True)
    await agent_runtime.create_handoff(session, run, payload.reason, automatic=False)
    return await agent_runtime.present_run(session, run)


@router.post(
    "/agent/runs/{run_id}/human-resolution",
    response_model=AgentRunResponse,
    tags=["agent"],
)
async def resolve_agent_handoff(
    run_id: str,
    payload: AgentHumanResolutionRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AgentRunResponse:
    run, _ = await agent_runtime.resolve_handoff(
        session, user_id, run_id, payload.action, payload.note
    )
    return await agent_runtime.present_run(session, run)


@router.get(
    "/agent/conversations/{conversation_id}",
    response_model=AgentConversationResponse,
    tags=["agent"],
)
async def get_agent_conversation(
    conversation_id: str,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> AgentConversationResponse:
    conversation = await agent_runtime.owned_conversation(
        session, user_id, conversation_id
    )
    return AgentConversationResponse.model_validate(conversation)
