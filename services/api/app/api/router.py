from fastapi import APIRouter

from app.api.routes import (
    agent,
    banking,
    channels,
    demo,
    experience,
    health,
    scheduled_tasks,
    security,
    system,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(system.router, prefix="/api/v1/system", tags=["system"])
api_router.include_router(experience.router, prefix="/api/v1")
api_router.include_router(banking.router, prefix="/api/v1")
api_router.include_router(channels.router, prefix="/api/v1")
api_router.include_router(security.router, prefix="/api/v1")
api_router.include_router(agent.router, prefix="/api/v1")
api_router.include_router(demo.router, prefix="/api/v1")
api_router.include_router(scheduled_tasks.router, prefix="/api/v1")
