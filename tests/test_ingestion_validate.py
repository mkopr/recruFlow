import logging
from unittest.mock import AsyncMock

import pytest
from app.ingestion.persist import normalize_and_validate
from app.schemas.offer import Offer


@pytest.mark.asyncio
async def test_normalize_and_validate_returns_offer_for_valid_payload() -> None:
    session = AsyncMock()
    result = await normalize_and_validate(
        session, {"source_id": 1, "title": "Backend Engineer", "company": "Acme"}
    )

    assert isinstance(result, Offer)
    assert result.title == "Backend Engineer"
    assert result.company == "Acme"
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_normalize_and_validate_returns_none_for_invalid_payload() -> None:
    session = AsyncMock()
    result = await normalize_and_validate(session, {"source_id": 1, "company": "Acme"})

    assert result is None


@pytest.mark.asyncio
async def test_normalize_and_validate_logs_warning_on_invalid_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # alembic's fileConfig (triggered by integration tests running command.upgrade
    # elsewhere in the same session) disables any pre-existing, unlisted logger
    # per stdlib logging.config semantics -- re-enable it so caplog can capture here
    # regardless of test execution order.
    logging.getLogger("app.ingestion.persist").disabled = False

    session = AsyncMock()
    with caplog.at_level(logging.WARNING, logger="app.ingestion.persist"):
        result = await normalize_and_validate(session, {"source_id": 1, "company": "Acme"})

    assert result is None
    assert len(caplog.records) == 1
    assert "skipping" in caplog.records[0].getMessage().lower()


@pytest.mark.asyncio
async def test_normalize_and_validate_records_ingestion_failure_on_invalid_payload() -> None:
    session = AsyncMock()

    result = await normalize_and_validate(session, {"source_id": 1, "company": "Acme"})

    assert result is None
    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    assert stmt.table.name == "ingestion_failures"
