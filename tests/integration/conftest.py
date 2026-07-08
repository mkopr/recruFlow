import os
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.db.models import MatchScore as MatchScoreModel
from app.db.models import Profile as ProfileModel
from app.db.session import get_engine, get_sessionmaker
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

# BUG28: defaults to the dedicated `db_test` compose service (port 5433), never the real `db`
# service (5432) that `make up` and a developer's real data live on -- this suite blanket-resets
# whole tables (e.g. reset_test_profiles) and must never be able to touch real state. CI
# overrides this via its own DATABASE_URL env var pointing at its ephemeral GitHub Actions
# postgres service, so `setdefault` is a no-op there.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://recruflow:recruflow@localhost:5433/recruflow_test"
)

REPO_ROOT = Path(__file__).parent.parent.parent


def alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return config


@pytest.fixture(scope="session", autouse=True)
def _default_test_database_url() -> None:
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://recruflow:recruflow@localhost:5433/recruflow_test"
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


async def reset_test_profiles(session: AsyncSession, names: list[str]) -> None:
    # Deactivating (rather than deleting) every row avoids tripping the
    # match_scores_profile_id_fkey constraint on profiles owned by unrelated
    # tests; deleting only the caller's own fixed names avoids unique-name
    # collisions on rerun without touching rows this suite doesn't own.
    #
    # BUG15: one of those names is `DEFAULT_PROFILE_NAME`, which is not
    # test-exclusive -- `upsert_active_profile` assigns it in real usage too,
    # so a real MatchScore (written by the batch-scoring job) can reference a
    # default-named profile this suite doesn't own. Delete any MatchScore
    # rows referencing the profiles about to be deleted first, or the profile
    # delete raises ForeignKeyViolationError.
    await session.execute(update(ProfileModel).values(is_active=False))
    profile_ids = (
        (await session.execute(select(ProfileModel.id).where(ProfileModel.name.in_(names))))
        .scalars()
        .all()
    )
    if profile_ids:
        await session.execute(
            delete(MatchScoreModel).where(MatchScoreModel.profile_id.in_(profile_ids))
        )
    await session.execute(delete(ProfileModel).where(ProfileModel.name.in_(names)))
    await session.commit()


@pytest_asyncio.fixture
async def scheduled_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
