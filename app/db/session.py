import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return url


def get_engine() -> AsyncEngine:
    return create_async_engine(get_database_url(), future=True)


def get_sessionmaker(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine or get_engine(), expire_on_commit=False)
