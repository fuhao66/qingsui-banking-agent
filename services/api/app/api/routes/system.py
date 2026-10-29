from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class ComponentStatus(BaseModel):
    name: str
    status: Literal["available", "planned"]
    stage: int


class SystemStatusResponse(BaseModel):
    environment: str
    version: str
    components: list[ComponentStatus]


@router.get("/status", response_model=SystemStatusResponse)
async def system_status() -> SystemStatusResponse:
    return SystemStatusResponse(
        environment=settings.app_env,
        version=settings.api_version,
        components=[
            ComponentStatus(name="api", status="available", stage=1),
            ComponentStatus(name="database", status="available", stage=2),
            ComponentStatus(name="banking_core", status="available", stage=2),
            ComponentStatus(name="policy_engine", status="available", stage=3),
            ComponentStatus(name="security_audit", status="available", stage=3),
            ComponentStatus(name="agent_graph", status="available", stage=4),
            ComponentStatus(name="human_handoff", status="available", stage=4),
            ComponentStatus(name="automated_evaluation", status="available", stage=7),
            ComponentStatus(name="demo_reset", status="available", stage=7),
            ComponentStatus(name="cross_scenario_planning", status="available", stage=8),
            ComponentStatus(name="scheduled_task_center", status="available", stage=8),
            ComponentStatus(name="public_experience_auth", status="available", stage=9),
            ComponentStatus(name="tenant_data_isolation", status="available", stage=9),
        ],
    )
