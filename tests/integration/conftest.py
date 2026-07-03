import os
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.db.session import get_engine, get_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

REPO_ROOT = Path(__file__).parent.parent.parent


def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return config


@pytest.fixture(scope="session", autouse=True)
def _default_test_database_url() -> None:
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://recruflow:recruflow@localhost:5432/recruflow"
    )


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(_default_test_database_url: None) -> None:
    # Runs synchronously (no event loop yet) so alembic's own asyncio.run()
    # in env.py never nests inside pytest-asyncio's loop.
    command.upgrade(alembic_config(), "head")


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = get_engine()
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    sessionmaker = get_sessionmaker(db_engine)
    async with sessionmaker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def scheduled_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
