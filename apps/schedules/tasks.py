"""The daily job as a Procrastinate periodic task (ADR 0005)."""

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.core.jobs import daily_cron
from apps.schedules.daily_job import run_daily_job

MORNING_HOUR = 6


def morning_cron(zone: str) -> str:
    """A daily cron expression for MORNING_HOUR in the zone, written in UTC."""
    return daily_cron(zone, MORNING_HOUR)


@app.periodic(cron=morning_cron(settings.TIME_ZONE))
@app.task(name="schedules.daily_job", queueing_lock="schedules.daily_job")
def daily_job(timestamp: int) -> None:  # noqa: ARG001
    """Run the daily job for today in Velora's time zone."""
    run_daily_job(timezone.localdate())
