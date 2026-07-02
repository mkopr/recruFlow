import pytest
from app.db.session import get_database_url, get_sessionmaker
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_get_database_url_returns_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = "postgresql+asyncpg://sentinel:sentinel@sentinel-host:5432/sentinel"
    monkeypatch.setenv("DATABASE_URL", sentinel)
    assert get_database_url() == sentinel


def test_get_database_url_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        get_database_url()


def test_get_sessionmaker_returns_async_sessionmaker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:1/x")
    sessionmaker = get_sessionmaker()
    assert isinstance(sessionmaker, async_sessionmaker)
