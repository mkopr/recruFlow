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
from app.scoring import batch
from app.scoring.batch import BatchScoringSummary
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://recruflow:recruflow@localhost:5432/recruflow"
)

# Force app.main (and every router module it imports, e.g. app.api.routes.scoring's own
# `from app.scoring.batch import run_batch_scoring`) to resolve its name-bound imports against
# the real, unpatched functions now, at collection time. Every test file's `client`/
# `scheduled_client` fixture does `from app.main import app` lazily, inside the test; if that
# import happened for the first time while `_stub_post_ingestion_batch_scoring` below had
# already monkeypatched `batch.run_batch_scoring`, the route module's own name-bound
# `run_batch_scoring` would permanently capture the stub instead of the real function, since
# Python resolves `from x import y` once, at import time, not as a live reference to `x.y`.
import app.main  # noqa: E402,F401

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


@pytest.fixture(autouse=True)
def _stub_post_ingestion_batch_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    # app.scheduler.service's post-ingestion hook (P3US25) calls this, unconditionally, on
    # every scheduler run. Tests that predate that hook (and every other scheduler/ingestion
    # test not specifically about batch scoring) never expect it to fire real LLM calls
    # against whatever active Profile happens to be left over from another test's state, so
    # this stubs it out by default; tests/integration/test_batch_scoring.py's own hook-wiring
    # tests re-monkeypatch this same attribute to observe the call instead.
    async def _noop(session: AsyncSession) -> BatchScoringSummary:
        return BatchScoringSummary(scored=0, skipped=0, failed=0)

    monkeypatch.setattr(batch, "run_batch_scoring", _noop)


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
