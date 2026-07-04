import logging

import httpx
import pytest
from app.connectors import nofluffjobs
from app.db.models import Source
from app.ingestion.normalize import NOFLUFFJOBS
from app.ingestion.types import IngestionResult as NoFluffJobsIngestionResult
from app.scheduler.service import ensure_sources_exist, run_source
from sqlalchemy.ext.asyncio import AsyncSession


def _enable_logger() -> None:
    logging.getLogger("app.scheduler.service").disabled = False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduled_run_with_zero_offers_logs_warning_and_flags_status(
    db_session: AsyncSession,
    scheduled_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()
    await ensure_sources_exist(db_session)
    await db_session.commit()

    async def _fake(session: AsyncSession, source: Source) -> NoFluffJobsIngestionResult:
        return NoFluffJobsIngestionResult(ok=True, fetched=0, created=0)

    monkeypatch.setattr(nofluffjobs, "run_nofluffjobs_ingestion", _fake)

    with caplog.at_level(logging.WARNING, logger="app.scheduler.service"):
        record = await run_source(NOFLUFFJOBS, trigger_type="automatic")

    assert record.status == "ok"
    assert record.warning is True
    assert record.fetched == 0
    assert any(r.levelno == logging.WARNING for r in caplog.records)

    status_response = await scheduled_client.get("/scheduler/status")
    entries = {entry["connector"]: entry for entry in status_response.json()["sources"]}
    entry = entries[NOFLUFFJOBS]
    assert entry["last_run_trigger_type"] == "automatic"
    assert entry["last_run_warning"] is True
