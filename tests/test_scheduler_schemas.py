from datetime import UTC, datetime

import pytest
from app.schemas.scheduler import (
    AutoFetchUpdateRequest,
    FetchRangeUpdateRequest,
    IntervalUpdateRequest,
)
from pydantic import ValidationError


def test_interval_update_request_rejects_seconds_below_60() -> None:
    with pytest.raises(ValidationError):
        IntervalUpdateRequest(seconds=30)


def test_interval_update_request_accepts_floor_value() -> None:
    IntervalUpdateRequest(seconds=60)


def test_interval_update_request_accepts_300() -> None:
    request = IntervalUpdateRequest(seconds=300)
    assert request.seconds == 300


def test_fetch_range_update_request_range_mode_requires_since() -> None:
    with pytest.raises(ValidationError):
        FetchRangeUpdateRequest(mode="range")


def test_fetch_range_update_request_rejects_since_after_until() -> None:
    with pytest.raises(ValidationError):
        FetchRangeUpdateRequest(
            mode="range",
            since=datetime(2026, 1, 8, tzinfo=UTC),
            until=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_fetch_range_update_request_accepts_since_equal_until() -> None:
    request = FetchRangeUpdateRequest(
        mode="range",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert request.since == request.until


def test_fetch_range_update_request_all_mode_ignores_since_until() -> None:
    request = FetchRangeUpdateRequest(
        mode="all",
        since=datetime(2026, 1, 1, tzinfo=UTC),
        until=datetime(2026, 1, 8, tzinfo=UTC),
    )
    assert request.since is None
    assert request.until is None


def test_auto_fetch_update_request_accepts_enabled_bool() -> None:
    assert AutoFetchUpdateRequest(enabled=False).enabled is False
