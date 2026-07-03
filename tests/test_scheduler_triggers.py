import logging

import pytest
from app.scheduler.triggers import DEFAULT_INTERVAL_SECONDS, parse_schedule
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


def _enable_logger() -> None:
    # see tests/test_ingestion_validate.py: alembic's fileConfig (triggered by
    # integration tests in the same session) can disable this logger.
    logging.getLogger("app.scheduler.triggers").disabled = False


def test_parse_schedule_interval_returns_interval_trigger() -> None:
    trigger = parse_schedule({"schedule": {"type": "interval", "seconds": 900}})

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 900


def test_parse_schedule_cron_returns_cron_trigger() -> None:
    trigger = parse_schedule({"schedule": {"type": "cron", "expression": "0 */2 * * *"}})

    assert isinstance(trigger, CronTrigger)


def test_parse_schedule_missing_schedule_key_falls_back_to_default_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.scheduler.triggers"):
        trigger = parse_schedule({})

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == DEFAULT_INTERVAL_SECONDS
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_parse_schedule_unknown_type_falls_back_to_default_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.scheduler.triggers"):
        trigger = parse_schedule({"schedule": {"type": "weekly"}})

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == DEFAULT_INTERVAL_SECONDS
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_parse_schedule_negative_interval_seconds_falls_back_to_default_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.scheduler.triggers"):
        trigger = parse_schedule({"schedule": {"type": "interval", "seconds": -5}})

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == DEFAULT_INTERVAL_SECONDS
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_parse_schedule_non_numeric_interval_seconds_falls_back_to_default_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.scheduler.triggers"):
        trigger = parse_schedule({"schedule": {"type": "interval", "seconds": "soon"}})

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == DEFAULT_INTERVAL_SECONDS
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_parse_schedule_unparseable_cron_expression_falls_back_to_default_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _enable_logger()

    with caplog.at_level(logging.WARNING, logger="app.scheduler.triggers"):
        trigger = parse_schedule({"schedule": {"type": "cron", "expression": "not a cron"}})

    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == DEFAULT_INTERVAL_SECONDS
    assert any(r.levelno == logging.WARNING for r in caplog.records)
