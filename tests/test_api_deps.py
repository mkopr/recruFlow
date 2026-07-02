import pytest
from app.api.deps import _get_sessionmaker, get_db
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_db_yields_async_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:1/x")
    _get_sessionmaker.cache_clear()

    gen = get_db()
    session = await anext(gen)
    try:
        assert isinstance(session, AsyncSession)
    finally:
        await gen.aclose()

    _get_sessionmaker.cache_clear()
