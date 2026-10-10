"""The daily job as a Procrastinate periodic task (ADR 0005)."""

from django.utils import timezone
from procrastinate.contrib.django import app

from apps.schedules.daily_job import run_daily_job


@app.periodic(cron="0 6 * * *")
@app.task(name="schedules.daily_job", queueing_lock="schedules.daily_job")
def daily_job(timestamp: int) -> None:  # noqa: ARG001
    """Run the daily job for today in Velora's time zone."""
    run_daily_job(timezone.localdate())
