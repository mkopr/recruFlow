from datetime import UTC, datetime, timedelta

from app.db.models import Offer as OfferModel
from app.scoring.batch import _in_fetch_range

NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _offer(posted_at: datetime | None) -> OfferModel:
    return OfferModel(posted_at=posted_at)


def test_in_fetch_range_mode_all_includes_any_posted_at() -> None:
    offer = _offer(NOW - timedelta(days=365))
    config_json = {"fetch_range": {"mode": "all"}}
    assert _in_fetch_range(offer, config_json) is True


def test_in_fetch_range_missing_fetch_range_key_includes_any_posted_at() -> None:
    offer = _offer(NOW - timedelta(days=365))
    assert _in_fetch_range(offer, {}) is True


def test_in_fetch_range_mode_range_excludes_before_since() -> None:
    offer = _offer(NOW - timedelta(days=10))
    config_json = {"fetch_range": {"mode": "range", "since": NOW.isoformat()}}
    assert _in_fetch_range(offer, config_json) is False


def test_in_fetch_range_mode_range_includes_within_bounds() -> None:
    offer = _offer(NOW)
    config_json = {
        "fetch_range": {
            "mode": "range",
            "since": (NOW - timedelta(days=5)).isoformat(),
            "until": (NOW + timedelta(days=5)).isoformat(),
        }
    }
    assert _in_fetch_range(offer, config_json) is True


def test_in_fetch_range_mode_range_excludes_after_until() -> None:
    offer = _offer(NOW)
    config_json = {"fetch_range": {"mode": "range", "until": (NOW - timedelta(days=1)).isoformat()}}
    assert _in_fetch_range(offer, config_json) is False


def test_in_fetch_range_null_posted_at_excluded_when_until_in_past() -> None:
    offer = _offer(None)
    now = datetime.now(UTC)
    config_json = {"fetch_range": {"mode": "range", "until": (now - timedelta(days=1)).isoformat()}}
    assert _in_fetch_range(offer, config_json) is False


def test_in_fetch_range_null_posted_at_included_when_no_until() -> None:
    offer = _offer(None)
    now = datetime.now(UTC)
    config_json = {
        "fetch_range": {"mode": "range", "since": (now - timedelta(days=30)).isoformat()}
    }
    assert _in_fetch_range(offer, config_json) is True
