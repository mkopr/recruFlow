from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import get_sessionmaker


@lru_cache
def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _get_sessionmaker()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]
