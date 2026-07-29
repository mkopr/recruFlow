import hashlib
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.dlq.types import FailureType

logger = logging.getLogger(__name__)


def build_detail_url_dedup_key(source_id: int, url: str) -> str:
    """Dedup key for a per-URL `DETAIL_FETCH_BLOCKED` row -- one row per failing posting, not
    per source (see `record_failure`'s docstring). A raw posting URL isn't guaranteed to fit
    `dedup_key`'s `String(255)` column, so it's hashed rather than embedded directly; sha256's
    64 hex characters plus the `source:{id}:detail_url:` prefix stay well under that limit.
    """
    return f"source:{source_id}:detail_url:{hashlib.sha256(url.encode()).hexdigest()}"


async def record_failure(
    session: AsyncSession,
    model_cls: type[Any],
    *,
    dedup_key: str,
    failure_type: FailureType,
    **fields: Any,
) -> None:
    """Upsert a dead letter row for `dedup_key`, reopening it if it was resolved.

    One row per failing resource (see DeadLetterMixin), not one row per occurrence --
    a recurring failure updates `failure_type`/`error_message`/`raw_payload`/`occurred_at`
    on the existing row rather than appending a sibling row. Never raises: a bug in the
    dead letter write path must not take down the ingestion/scoring call site it's
    instrumenting.

    `failure_type` is pulled out of the otherwise-generic `**fields` catch-all so
    every call site is checked against `FailureType` -- the same vocabulary `app.dlq.retry`
    dispatches on -- rather than a bare string only `RETRY_HANDLERS` happens to agree with.
    """
    try:
        stmt = (
            pg_insert(model_cls)
            .values(
                dedup_key=dedup_key,
                status="open",
                occurred_at=func.now(),
                failure_type=failure_type,
                **fields,
            )
            .on_conflict_do_update(
                index_elements=["dedup_key"],
                set_={
                    **fields,
                    "failure_type": failure_type,
                    "status": "open",
                    "resolved_at": None,
                    "occurred_at": func.now(),
                },
            )
        )
        await session.execute(stmt)
    except Exception:
        logger.error(
            "failed to record %s failure: dedup_key=%r failure_type=%r fields=%r",
            model_cls.__name__,
            dedup_key,
            failure_type,
            fields,
            exc_info=True,
        )


async def list_failures(
    session: AsyncSession,
    model_cls: type[Any],
    *,
    limit: int,
    offset: int,
    filters: dict[str, Any],
) -> tuple[Sequence[Any], int]:
    stmt = select(model_cls)
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(getattr(model_cls, column) == value)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    page_stmt = stmt.order_by(model_cls.occurred_at.desc()).limit(limit).offset(offset)
    rows = (await session.scalars(page_stmt)).all()
    return rows, total
