from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_demo_user_id
from app.domain.schemas import DemoResetRequest, DemoResetResponse
from app.services.demo import reset_demo_data

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
DemoUserId = Annotated[str, Depends(get_demo_user_id)]


@router.post(
    "/demo/reset",
    response_model=DemoResetResponse,
    status_code=status.HTTP_200_OK,
    tags=["demo"],
)
async def reset_demo(
    payload: DemoResetRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> DemoResetResponse:
    del payload
    reset_at, audit_event_id = await reset_demo_data(session, user_id)
    return DemoResetResponse(
        status="reset",
        reset_at=reset_at,
        user_id=user_id,
        audit_event_id=audit_event_id,
    )
