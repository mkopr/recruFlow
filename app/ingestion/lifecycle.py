from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source
from app.db.session import get_engine, get_sessionmaker
from app.ingestion.registry import dispatch_ingestion, resolve_source_by_connector
from app.ingestion.types import IngestionResult

BeforeDispatch = Callable[[AsyncSession, Source], Awaitable[None]]
OnSuccess = Callable[[AsyncSession, Source, IngestionResult], Awaitable[None]]
OnError = Callable[[AsyncSession, Source, Exception], Awaitable[None]]


async def run_with_lifecycle(
    connector: str,
    *,
    force_refresh: bool = False,
    before_dispatch: BeforeDispatch | None = None,
    on_success: OnSuccess,
    on_error: OnError,
) -> tuple[Source, IngestionResult | None, Exception | None]:
    """Own the engine/session/dispatch lifecycle shared by every "run a connector" flow.

    `on_success` runs, then the session is committed. `on_error` owns rollback/commit itself
    since callers disagree on which — nothing is committed on its behalf.
    """
    engine = get_engine()
    try:
        sessionmaker = get_sessionmaker(engine)
        async with sessionmaker() as session:
            source = await resolve_source_by_connector(session, connector)

            if before_dispatch is not None:
                await before_dispatch(session, source)
                await session.commit()

            try:
                result = await dispatch_ingestion(session, source, force_refresh=force_refresh)
            except Exception as exc:
                await on_error(session, source, exc)
                return source, None, exc

            await on_success(session, source, result)
            await session.commit()
            return source, result, None
    finally:
        await engine.dispose()
