"""Keeping one failure in the daily job from stopping the rest of it."""

import logging
import traceback
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.db import transaction as db_transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from django.db.models import Model

logger = logging.getLogger("daily_job")


class ItemsFailedError(Exception):
    """Some of a step's items failed; each is already logged."""

    def __init__(self, step: str, failures: list[str]) -> None:
        super().__init__(step)
        self.failures = failures


def run_each[T: Model](
    step: str, items: Iterable[T], action: Callable[[T], object]
) -> None:
    """Run the action on each item, rolling back only the items that fail."""
    failures = []
    for item in items:
        try:
            with db_transaction.atomic():
                action(item)
        except Exception:
            logger.exception("%s failed for %s %s", step, type(item).__name__, item.pk)
            failures.append(
                f"{step} failed for {type(item).__name__} {item.pk}\n"
                f"{traceback.format_exc()}"
            )
    if failures:
        raise ItemsFailedError(step, failures)


def daily_cron(zone: str, hour: int) -> str:
    """A daily cron expression for the hour in the zone, written in UTC.

    Procrastinate reads cron expressions in UTC and takes no time zone. The
    zone's offset is read when the worker starts, so a daylight saving change
    shifts the run by an hour until the worker restarts.
    """
    offset = datetime.now(ZoneInfo(zone)).utcoffset() or timedelta()
    minutes = (hour * 60 - int(offset.total_seconds()) // 60) % (24 * 60)
    return f"{minutes % 60} {minutes // 60} * * *"
