import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.ingestion import runner as runner_module
from app.ingestion.runner import run_paginated_ingestion


@pytest.mark.asyncio
async def test_run_paginated_ingestion_records_page_fetch_failure_after_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_ingest_offer(
        session: object, mapped_fields: dict[str, Any], raw_payload: dict[str, Any]
    ) -> tuple[object, bool]:
        return object(), True

    monkeypatch.setattr(runner_module, "ingest_offer", _fake_ingest_offer)

    pages = {0: ([{"title": "x"}], "cursor1"), 1: None}

    def fetch_page(cursor: Any, page_size: int) -> Any:
        page_index = 0 if cursor is None else 1
        return pages[page_index]

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
    )

    assert result.ok is True
    session.execute.assert_called_once()
    stmt = session.execute.call_args[0][0]
    assert stmt.table.name == "ingestion_failures"


@pytest.mark.asyncio
async def test_run_paginated_ingestion_first_page_failure_does_not_record_anything() -> None:
    def fetch_page(cursor: Any, page_size: int) -> Any:
        return None

    session = AsyncMock()

    result = await run_paginated_ingestion(
        session,
        source_id=7,
        source_name="test-source",
        fetch_page=fetch_page,
        map_offer=lambda source_id, raw: raw,
        initial_cursor=None,
        page_size=10,
        max_pages=5,
        already_seen_stop_threshold=20,
        force_refresh=False,
        logger=logging.getLogger("test"),
    )

    assert result.ok is False
    session.execute.assert_not_called()
