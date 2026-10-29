from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionFactory
from app.db.models import ExperienceSession
from app.domain.constants import DEMO_USER_ID
from app.services.experience import auth_error, authenticate_token


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def get_demo_user_id(
    session: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_demo_user_id: Annotated[str | None, Header()] = None,
) -> str:
    if settings.public_demo_mode:
        if not authorization or not authorization.startswith("Bearer "):
            raise auth_error("EXPERIENCE_TOKEN_REQUIRED", "请先使用邀请码登录体验。")
        experience = await authenticate_token(session, authorization.removeprefix("Bearer ").strip())
        return experience.user_id
    return x_demo_user_id or DEMO_USER_ID


async def get_experience_session(
    session: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> ExperienceSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise auth_error("EXPERIENCE_TOKEN_REQUIRED", "请先使用邀请码登录体验。")
    return await authenticate_token(session, authorization.removeprefix("Bearer ").strip())
