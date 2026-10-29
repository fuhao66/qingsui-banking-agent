from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.database import database_is_ready

router = APIRouter(prefix="/health")


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "degraded"]
    dependencies: dict[str, bool]


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(service=settings.app_name, version=settings.api_version)


@router.get("/ready", response_model=ReadyResponse)
async def ready(response: Response) -> ReadyResponse:
    database_ready = await database_is_ready()
    redis_ready = False
    redis = Redis.from_url(settings.redis_url)
    try:
        redis_ready = bool(await redis.ping())
    except RedisError:
        redis_ready = False
    finally:
        await redis.aclose()

    dependencies = {"postgres": database_ready, "redis": redis_ready}
    is_ready = all(dependencies.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if is_ready else "degraded",
        dependencies=dependencies,
    )
