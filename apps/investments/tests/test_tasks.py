from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.core.jobs import daily_cron
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tasks import NIGHT_HOUR, backfill_prices, nightly_prices
from apps.investments.tests.conftest import make_broker, record_event, row

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.tests.conftest import FakePriceSource

FUND = "INF209KA12Z1"

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


def test_the_backfill_task_fills_prices_up_to_today(
    monkeypatch: pytest.MonkeyPatch, fake_prices: FakePriceSource
) -> None:
    today = date(2026, 3, 4)
    monkeypatch.setattr(timezone, "localdate", lambda: today)
    Instrument.objects.create(isin=FUND, name="A fund", kind="mutual_fund")
    InvestmentEvent.objects.create(
        account=make_broker(),
        instrument=Instrument.objects.get(),
        kind="buy",
        date=today,
        units=1,
        price=10,
        amount=10,
    )
    fake_prices.history = [row(FUND, "A fund", "mutual_fund", "10", today)]

    backfill_prices()

    assert Instrument.objects.get().prices.get().date == today


def test_recording_a_buy_queues_one_backfill(signed_in: Client) -> None:
    Instrument.objects.create(isin=FUND, name="A fund", kind="mutual_fund")
    broker = make_broker()

    for _ in range(2):
        record_event(signed_in, broker, "buy", FUND, units="1", price="10", amount="10")

    assert ProcrastinateJob.objects.get().task_name == "investments.backfill_prices"


def test_recording_a_sell_queues_no_backfill(signed_in: Client) -> None:
    Instrument.objects.create(isin=FUND, name="A fund", kind="mutual_fund")
    broker = make_broker()
    record_event(signed_in, broker, "buy", FUND, units="1", price="10", amount="10")
    ProcrastinateJob.objects.all().delete()

    record_event(signed_in, broker, "sell", FUND, units="1", price="10", amount="10")

    assert not ProcrastinateJob.objects.exists()
