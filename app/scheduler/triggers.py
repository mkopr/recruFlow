import logging
from typing import Any

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 3600


def _default_trigger() -> IntervalTrigger:
    return IntervalTrigger(seconds=DEFAULT_INTERVAL_SECONDS)


def _parse_interval(schedule: dict[str, Any]) -> BaseTrigger | None:
    seconds = schedule.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds <= 0:
        logger.warning("invalid interval schedule seconds: %r", seconds)
        return None
    return IntervalTrigger(seconds=seconds)


def _parse_cron(schedule: dict[str, Any]) -> BaseTrigger | None:
    expression = schedule.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        logger.warning("invalid cron schedule expression: %r", expression)
        return None
    try:
        return CronTrigger.from_crontab(expression)
    except ValueError:
        logger.warning("unparseable cron schedule expression: %r", expression)
        return None


def parse_schedule(config_json: dict[str, Any] | None) -> BaseTrigger:
    if not isinstance(config_json, dict):
        logger.warning("config_json is not a dict, falling back to default schedule")
        return _default_trigger()

    schedule = config_json.get("schedule")
    if not isinstance(schedule, dict):
        logger.warning("missing or malformed schedule key, falling back to default schedule")
        return _default_trigger()

    schedule_type = schedule.get("type")
    trigger: BaseTrigger | None
    if schedule_type == "interval":
        trigger = _parse_interval(schedule)
    elif schedule_type == "cron":
        trigger = _parse_cron(schedule)
    else:
        logger.warning("unknown schedule type: %r", schedule_type)
        trigger = None

    return trigger if trigger is not None else _default_trigger()
