import pytest
from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.quick_add.models import Draft
from apps.schedules.tasks import daily_job, morning_cron
from apps.schedules.tests.conftest import make_schedule

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("zone", "cron"),
    [
        ("UTC", "0 6 * * *"),
        ("Asia/Kolkata", "30 0 * * *"),
        ("Pacific/Honolulu", "0 16 * * *"),
    ],
)
def test_six_in_the_morning_is_read_in_the_time_zone(zone: str, cron: str) -> None:
    assert morning_cron(zone) == cron


def test_the_daily_job_runs_every_morning_in_velora_time_zone() -> None:
    periodic = [
        task.cron
        for task in app.periodic_registry.periodic_tasks.values()
        if task.task is daily_job
    ]

    assert periodic == [morning_cron(settings.TIME_ZONE)]


def test_the_task_runs_the_daily_job_for_today() -> None:
    make_schedule(start_date=timezone.localdate())

    daily_job(timestamp=0)

    assert Draft.objects.get().date == timezone.localdate()
