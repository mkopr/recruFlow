from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from app.connectors.http import BlockedFetchError
from app.dlq import retry
from app.dlq.retry import RETRY_HANDLERS, UnknownFailureTypeError, perform_retry
from app.dlq.types import FailureType


def test_retry_handlers_covers_every_failure_type() -> None:
    # The closest thing to a compile-time exhaustiveness check a plain dict literal gets --
    # this is the guardrail that would fail at collection time if DETAIL_FETCH_BLOCKED were
    # ever added to FailureType without a matching RETRY_HANDLERS entry.
    assert set(RETRY_HANDLERS) == set(FailureType)


@pytest.mark.asyncio
async def test_perform_retry_raises_named_error_for_unrecognized_failure_type() -> None:
    session = AsyncMock()
    row = SimpleNamespace(failure_type="not_a_real_failure_type")

    with pytest.raises(UnknownFailureTypeError) as exc_info:
        await perform_retry(session, row)

    assert exc_info.value.failure_type == "not_a_real_failure_type"
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_retry_detail_fetch_blocked_returns_false_when_url_is_none() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=SimpleNamespace(id=1, connector="bulldogjob"))
    row = SimpleNamespace(
        source_id=1,
        url=None,
        failure_type=FailureType.DETAIL_FETCH_BLOCKED,
        status="open",
        error_message="old",
    )

    await perform_retry(session, row)

    assert row.status == "open"
    assert "no url stored" in row.error_message


@pytest.mark.asyncio
async def test_retry_detail_fetch_blocked_dispatches_to_connector_specs_detail_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    source = SimpleNamespace(id=1, connector="bulldogjob")
    session.get = AsyncMock(return_value=source)

    detail_retry = AsyncMock(return_value=True)
    fake_spec = SimpleNamespace(detail_retry=detail_retry)
    monkeypatch.setattr(retry, "CONNECTOR_REGISTRY", {"bulldogjob": fake_spec})

    row = SimpleNamespace(
        source_id=1,
        url="https://example.test/jobs/1",
        failure_type=FailureType.DETAIL_FETCH_BLOCKED,
        status="open",
        resolved_at=None,
        error_message="old",
    )

    await perform_retry(session, row)

    detail_retry.assert_awaited_once_with(session, source, row.url)
    assert row.status == "resolved"
    assert row.resolved_at is not None


@pytest.mark.asyncio
async def test_retry_detail_fetch_blocked_still_blocked_marks_row_open_with_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    source = SimpleNamespace(id=1, connector="bulldogjob")
    session.get = AsyncMock(return_value=source)

    async def _raise_blocked(session: Any, source: Any, url: str) -> bool:
        raise BlockedFetchError(403)

    fake_spec = SimpleNamespace(detail_retry=_raise_blocked)
    monkeypatch.setattr(retry, "CONNECTOR_REGISTRY", {"bulldogjob": fake_spec})

    row = SimpleNamespace(
        source_id=1,
        url="https://example.test/jobs/1",
        failure_type=FailureType.DETAIL_FETCH_BLOCKED,
        status="open",
        error_message="old",
    )

    await perform_retry(session, row)

    assert row.status == "open"
    assert "403" in row.error_message
