import pytest
from app.schemas.scheduler import IntervalUpdateRequest
from pydantic import ValidationError


def test_interval_update_request_rejects_seconds_below_60() -> None:
    with pytest.raises(ValidationError):
        IntervalUpdateRequest(seconds=30)


def test_interval_update_request_accepts_floor_value() -> None:
    IntervalUpdateRequest(seconds=60)


def test_interval_update_request_accepts_300() -> None:
    request = IntervalUpdateRequest(seconds=300)
    assert request.seconds == 300
