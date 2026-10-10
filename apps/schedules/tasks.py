"""The daily job as a Procrastinate periodic task (ADR 0005)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.schedules.daily_job import run_daily_job

MORNING_HOUR = 6


def morning_cron(zone: str) -> str:
    """A daily cron expression for MORNING_HOUR in the zone, written in UTC.

    Procrastinate reads cron expressions in UTC and takes no time zone. The
    zone's offset is read when the worker starts, so a daylight saving change
    shifts the run by an hour until the worker restarts.
    """
    offset = datetime.now(ZoneInfo(zone)).utcoffset() or timedelta()
    minutes = (MORNING_HOUR * 60 - int(offset.total_seconds()) // 60) % (24 * 60)
    return f"{minutes % 60} {minutes // 60} * * *"


@app.periodic(cron=morning_cron(settings.TIME_ZONE))
@app.task(name="schedules.daily_job", queueing_lock="schedules.daily_job")
def daily_job(timestamp: int) -> None:  # noqa: ARG001
    """Run the daily job for today in Velora's time zone."""
    run_daily_job(timezone.localdate())
