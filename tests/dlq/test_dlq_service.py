import logging
from unittest.mock import AsyncMock

import pytest
from app.db.models import IngestionFailure, ScoringFailure
from app.dlq.service import record_failure
from app.dlq.types import FailureType


@pytest.mark.asyncio
async def test_record_failure_executes_upsert_against_the_right_table() -> None:
    session = AsyncMock()

    await record_failure(
        session,
        IngestionFailure,
        dedup_key="source:1",
        source_id=1,
        failure_type=FailureType.PAGE_FETCH_FAILED,
        error_message="bad",
    )

    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    assert stmt.table.name == "ingestion_failures"


@pytest.mark.asyncio
async def test_record_failure_never_raises_when_session_execute_raises() -> None:
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("boom")

    await record_failure(
        session,
        ScoringFailure,
        dedup_key="offer:1:profile:2",
        offer_id=1,
        profile_id=2,
        failure_type=FailureType.SCORING_FAILED,
        error_message="x",
    )


@pytest.mark.asyncio
async def test_record_failure_logs_error_on_failure(caplog: pytest.LogCaptureFixture) -> None:
    logging.getLogger("app.dlq.service").disabled = False
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="app.dlq.service"):
        await record_failure(
            session,
            ScoringFailure,
            dedup_key="offer:1:profile:2",
            offer_id=1,
            profile_id=2,
            failure_type=FailureType.SCORING_FAILED,
            error_message="x",
        )

    assert any(r.levelno == logging.ERROR for r in caplog.records)
