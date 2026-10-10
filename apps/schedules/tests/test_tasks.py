import pytest
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.quick_add.models import Draft
from apps.schedules.tasks import daily_job
from apps.schedules.tests.conftest import make_schedule

pytestmark = pytest.mark.django_db


def test_the_daily_job_runs_every_morning() -> None:
    periodic = [
        task.cron
        for task in app.periodic_registry.periodic_tasks.values()
        if task.task is daily_job
    ]

    assert periodic == ["0 6 * * *"]


def test_the_task_runs_the_daily_job_for_today() -> None:
    make_schedule(start_date=timezone.localdate())

    daily_job(timestamp=0)

    assert Draft.objects.get().date == timezone.localdate()
