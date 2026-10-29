import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.dependencies import get_db
from app.api.routes import channels as channel_routes
from app.db.base import Base
from app.db.seed import seed_demo_data
from app.main import app


@pytest.fixture()
def api_client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = tmp_path / "banking-agent-test.db"
    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def prepare_database() -> None:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with test_session_factory() as session:
            await seed_demo_data(session)

    async def override_database():
        async with test_session_factory() as session:
            yield session

    asyncio.run(prepare_database())
    app.dependency_overrides[get_db] = override_database
    original_channel_factory = channel_routes.SessionFactory
    channel_routes.SessionFactory = test_session_factory
    with TestClient(app) as client:
        yield client
    channel_routes.SessionFactory = original_channel_factory
    app.dependency_overrides.clear()
    asyncio.run(test_engine.dispose())
