from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_demo_user_id
from app.domain.schemas import (
    ScheduledTaskActionRequest,
    ScheduledTaskListResponse,
    ScheduledTaskResponse,
)
from app.services import scheduled_tasks as task_service

router = APIRouter()
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
DemoUserId = Annotated[str, Depends(get_demo_user_id)]


@router.get("/scheduled-tasks", response_model=ScheduledTaskListResponse, tags=["tasks"])
async def scheduled_tasks(
    session: DatabaseSession,
    user_id: DemoUserId,
    task_status: Annotated[
        str | None,
        Query(alias="status", pattern=r"^(scheduled|paused|cancelled|completed|failed)$"),
    ] = None,
) -> ScheduledTaskListResponse:
    rows = await task_service.list_user_tasks(session, user_id, task_status)
    reserved = sum(
        (row.reserved_amount for row in rows if row.status in task_service.ACTIVE_STATUSES),
        Decimal(0),
    )
    return ScheduledTaskListResponse(
        items=[ScheduledTaskResponse.model_validate(row) for row in rows],
        total=len(rows),
        active_reserved_amount=reserved,
    )


@router.get(
    "/scheduled-tasks/{task_id}", response_model=ScheduledTaskResponse, tags=["tasks"]
)
async def scheduled_task(
    task_id: str, session: DatabaseSession, user_id: DemoUserId
) -> ScheduledTaskResponse:
    row = await task_service.get_owned_task(session, user_id, task_id)
    return ScheduledTaskResponse.model_validate(row)


@router.post(
    "/scheduled-tasks/{task_id}/actions",
    response_model=ScheduledTaskResponse,
    tags=["tasks"],
)
async def update_scheduled_task(
    task_id: str,
    payload: ScheduledTaskActionRequest,
    session: DatabaseSession,
    user_id: DemoUserId,
) -> ScheduledTaskResponse:
    row = await task_service.transition_task(session, user_id, task_id, payload.action)
    return ScheduledTaskResponse.model_validate(row)
