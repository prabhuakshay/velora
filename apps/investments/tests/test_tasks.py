from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.core.jobs import daily_cron
from apps.investments.models import Instrument
from apps.investments.tasks import NIGHT_HOUR, nightly_prices
from apps.investments.tests.conftest import row

if TYPE_CHECKING:
    from apps.investments.tests.conftest import FakePriceSource

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("zone", "hour", "cron"),
    [
        ("UTC", 23, "0 23 * * *"),
        ("Asia/Kolkata", 23, "30 17 * * *"),
        ("Asia/Kolkata", 2, "30 20 * * *"),
    ],
)
def test_the_hour_is_read_in_the_time_zone(zone: str, hour: int, cron: str) -> None:
    assert daily_cron(zone, hour) == cron


def test_prices_are_fetched_every_night_in_velora_time_zone() -> None:
    periodic = [
        task.cron
        for task in app.periodic_registry.periodic_tasks.values()
        if task.task is nightly_prices
    ]

    assert periodic == [daily_cron(settings.TIME_ZONE, NIGHT_HOUR)]


def test_the_task_stores_today_prices(fake_prices: FakePriceSource) -> None:
    today = timezone.localdate()
    fake_prices.amfi = [row("INF209KA12Z1", "A fund", "mutual_fund", "10", today)]

    nightly_prices(timestamp=0)

    assert Instrument.objects.get().prices.get().date == today
