import logging
from unittest.mock import AsyncMock

import pytest
from app.db.models import IngestionFailure, ScoringFailure
from app.dlq.service import build_detail_url_dedup_key, record_failure
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


def test_build_detail_url_dedup_key_is_stable_and_prefixed_by_source() -> None:
    url = "https://rocketjobs.pl/oferta-pracy/example-posting"

    key_a = build_detail_url_dedup_key(1, url)
    key_b = build_detail_url_dedup_key(1, url)

    assert key_a == key_b
    assert key_a.startswith("source:1:detail_url:")


def test_build_detail_url_dedup_key_differs_across_urls_and_sources() -> None:
    url_a = "https://rocketjobs.pl/oferta-pracy/a"
    url_b = "https://rocketjobs.pl/oferta-pracy/b"

    assert build_detail_url_dedup_key(1, url_a) != build_detail_url_dedup_key(1, url_b)
    assert build_detail_url_dedup_key(1, url_a) != build_detail_url_dedup_key(2, url_a)


def test_build_detail_url_dedup_key_stays_under_255_chars_for_a_very_long_url() -> None:
    url = "https://rocketjobs.pl/oferta-pracy/" + ("x" * 2000)

    key = build_detail_url_dedup_key(123456, url)

    assert len(key) <= 255
