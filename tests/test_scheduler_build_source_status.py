from datetime import UTC, datetime

from app.db.models import SchedulerRun, Source
from app.scheduler.runs import build_source_status


def _source(**overrides: object) -> Source:
    defaults: dict[str, object] = dict(
        id=1,
        name="justjoinit",
        connector="justjoinit",
        config_json={
            "schedule": {"type": "interval", "seconds": 900},
            "fetch_range": {"mode": "range", "since": "2026-01-01T00:00:00Z", "until": None},
            "auto_fetch_enabled": True,
        },
        last_fetched_at=None,
    )
    defaults.update(overrides)
    return Source(**defaults)


def test_build_source_status_with_no_last_run_returns_null_run_fields() -> None:
    source = _source()

    status = build_source_status(source, None)

    assert status.source_id == 1
    assert status.connector == "justjoinit"
    assert status.name == "justjoinit"
    assert status.schedule == {"type": "interval", "seconds": 900}
    assert status.fetch_range == {"mode": "range", "since": "2026-01-01T00:00:00Z", "until": None}
    assert status.auto_fetch_enabled is True
    assert status.last_fetched_at is None
    assert status.last_run_id is None
    assert status.last_run_started_at is None
    assert status.last_run_finished_at is None
    assert status.last_run_status is None
    assert status.last_run_trigger_type is None
    assert status.last_run_fetched is None
    assert status.last_run_created is None
    assert status.last_run_warning is False
    assert status.last_run_error_message is None


def test_build_source_status_with_last_run_maps_all_run_fields() -> None:
    source = _source()
    started = datetime(2026, 7, 7, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 7, 7, 10, 5, tzinfo=UTC)
    last_run = SchedulerRun(
        id=42,
        source_id=1,
        trigger_type="scheduled",
        status="ok",
        fetched_count=10,
        created_count=3,
        warning=True,
        error_message=None,
        started_at=started,
        finished_at=finished,
    )

    status = build_source_status(source, last_run)

    assert status.last_run_id == 42
    assert status.last_run_started_at == started
    assert status.last_run_finished_at == finished
    assert status.last_run_status == "ok"
    assert status.last_run_trigger_type == "scheduled"
    assert status.last_run_fetched == 10
    assert status.last_run_created == 3
    assert status.last_run_warning is True
    assert status.last_run_error_message is None


def test_build_source_status_includes_fetch_range_and_auto_fetch_enabled() -> None:
    fetch_range = {
        "mode": "range",
        "since": "2026-06-01T00:00:00Z",
        "until": "2026-06-30T00:00:00Z",
    }
    source = _source(
        config_json={
            "schedule": {"type": "interval", "seconds": 900},
            "fetch_range": fetch_range,
            "auto_fetch_enabled": False,
        }
    )

    status = build_source_status(source, None)

    assert status.fetch_range == fetch_range
    assert status.auto_fetch_enabled is False


def test_build_source_status_defaults_auto_fetch_enabled_true_when_key_absent() -> None:
    source = _source(config_json={"schedule": {"type": "interval", "seconds": 900}})

    status = build_source_status(source, None)

    assert status.auto_fetch_enabled is True
    assert status.fetch_range == {}


def test_build_source_status_asserts_connector_is_present() -> None:
    source = _source(connector=None)

    try:
        build_source_status(source, None)
    except AssertionError:
        pass
    else:
        raise AssertionError("expected build_source_status to assert connector is not None")
