import hmac
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_experience_session
from app.core.config import settings
from app.db.models import AgentRun, ExperienceSession, ScheduledTask
from app.domain.schemas import (
    ExperienceAdminStatsResponse,
    ExperienceLoginRequest,
    ExperienceLoginResponse,
    ExperienceProfileResponse,
)
from app.services.experience import create_experience_session, revoke_session

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
CurrentExperience = Annotated[ExperienceSession, Depends(get_experience_session)]


@router.post("/auth/experience", response_model=ExperienceLoginResponse, tags=["experience"])
async def experience_login(
    payload: ExperienceLoginRequest, session: DatabaseSession
) -> ExperienceLoginResponse:
    token, experience, user = await create_experience_session(
        session, payload.invite_code, payload.display_name.strip()
    )
    return ExperienceLoginResponse(
        access_token=token,
        expires_at=experience.expires_at,
        user_id=user.id,
        display_name=user.display_name,
    )


@router.get("/auth/me", response_model=ExperienceProfileResponse, tags=["experience"])
async def experience_profile(experience: CurrentExperience) -> ExperienceProfileResponse:
    return ExperienceProfileResponse(
        user_id=experience.user_id,
        display_name=experience.display_name,
        expires_at=experience.expires_at,
        request_count=experience.request_count,
    )


@router.post("/auth/logout", tags=["experience"])
async def experience_logout(
    session: DatabaseSession, experience: CurrentExperience
) -> dict[str, str]:
    await revoke_session(session, experience)
    return {"status": "logged_out"}


@router.get(
    "/admin/experience-stats",
    response_model=ExperienceAdminStatsResponse,
    tags=["experience-admin"],
)
async def experience_stats(
    session: DatabaseSession,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> ExperienceAdminStatsResponse:
    if not settings.admin_api_token or not x_admin_token or not hmac.compare_digest(
        x_admin_token, settings.admin_api_token
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ADMIN_TOKEN_INVALID", "message": "管理员凭证无效。"},
        )
    now = datetime.now(UTC)
    total_sessions = int(
        await session.scalar(select(func.count()).select_from(ExperienceSession)) or 0
    )
    active_sessions = int(
        await session.scalar(
            select(func.count())
            .select_from(ExperienceSession)
            .where(ExperienceSession.revoked.is_(False), ExperienceSession.expires_at > now)
        )
        or 0
    )
    total_requests = int(
        await session.scalar(select(func.coalesce(func.sum(ExperienceSession.request_count), 0)))
        or 0
    )
    experience_user_ids = select(ExperienceSession.user_id)
    agent_runs = int(
        await session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.user_id.in_(experience_user_ids))
        )
        or 0
    )
    scheduled_tasks = int(
        await session.scalar(
            select(func.count())
            .select_from(ScheduledTask)
            .where(ScheduledTask.user_id.in_(experience_user_ids))
        )
        or 0
    )
    recent = list(
        await session.scalars(
            select(ExperienceSession).order_by(ExperienceSession.last_seen_at.desc()).limit(20)
        )
    )
    return ExperienceAdminStatsResponse(
        total_sessions=total_sessions,
        active_sessions=active_sessions,
        total_requests=total_requests,
        agent_runs=agent_runs,
        scheduled_tasks=scheduled_tasks,
        recent_sessions=[
            {
                "id": item.id,
                "display_name": item.display_name,
                "request_count": item.request_count,
                "revoked": item.revoked,
                "created_at": item.created_at,
                "last_seen_at": item.last_seen_at,
                "expires_at": item.expires_at,
            }
            for item in recent
        ],
    )
