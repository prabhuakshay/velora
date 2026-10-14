from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from procrastinate.contrib.django import app
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.core.jobs import daily_cron
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.nightly import PriceFetchError
from apps.investments.tasks import (
    NIGHT_HOUR,
    backfill_prices,
    nightly_prices,
    refresh_prices,
)
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


def held_fund(today: date) -> None:
    InvestmentEvent.objects.create(
        account=make_broker(),
        instrument=Instrument.objects.create(
            isin=FUND, name="A fund", kind="mutual_fund"
        ),
        kind="buy",
        date=today - timedelta(days=3),
        units=1,
        price=10,
        amount=10,
    )


def test_refreshing_fetches_today_and_fills_past_prices(
    monkeypatch: pytest.MonkeyPatch, fake_prices: FakePriceSource
) -> None:
    today = date(2026, 3, 4)
    monkeypatch.setattr(timezone, "localdate", lambda: today)
    held_fund(today)
    fake_prices.amfi = [row(FUND, "A fund", "mutual_fund", "12", today)]
    fake_prices.history = [row(FUND, "A fund", "mutual_fund", "10", date(2026, 3, 2))]

    refresh_prices()

    prices = Instrument.objects.get().prices.order_by("date")
    assert list(prices.values_list("date", flat=True)) == [date(2026, 3, 2), today]


def test_refreshing_still_backfills_when_today_fetch_fails(
    monkeypatch: pytest.MonkeyPatch, fake_prices: FakePriceSource
) -> None:
    today = date(2026, 3, 4)
    monkeypatch.setattr(timezone, "localdate", lambda: today)
    held_fund(today)
    fake_prices.amfi = OSError("AMFI is down")
    fake_prices.history = [row(FUND, "A fund", "mutual_fund", "10", date(2026, 3, 2))]

    with pytest.raises(PriceFetchError):
        refresh_prices()

    assert Instrument.objects.get().prices.get().date == date(2026, 3, 2)


def test_refreshing_raises_when_the_backfill_fails(
    monkeypatch: pytest.MonkeyPatch, fake_prices: FakePriceSource
) -> None:
    today = date(2026, 3, 4)
    monkeypatch.setattr(timezone, "localdate", lambda: today)
    held_fund(today)
    fake_prices.amfi_history = OSError("AMFI archive is down")

    with pytest.raises(PriceFetchError):
        refresh_prices()


def test_refreshing_names_both_failures(
    monkeypatch: pytest.MonkeyPatch, fake_prices: FakePriceSource
) -> None:
    today = date(2026, 3, 4)
    monkeypatch.setattr(timezone, "localdate", lambda: today)
    held_fund(today)
    fake_prices.nse = OSError("NSE is down")
    fake_prices.amfi_history = OSError("AMFI archive is down")

    with pytest.raises(PriceFetchError, match="NSE, AMFI"):
        refresh_prices()


def test_the_refresh_button_queues_one_refresh(signed_in: Client) -> None:
    for _ in range(2):
        response = signed_in.post(reverse("investments_refresh_prices"), follow=True)

    assert response.redirect_chain == [(reverse("investments_overview"), 302)]
    assert "Refreshing Prices" in response.content.decode()
    assert ProcrastinateJob.objects.get().task_name == "investments.refresh_prices"


def test_refreshing_is_post_only(signed_in: Client) -> None:
    assert signed_in.get(reverse("investments_refresh_prices")).status_code == 405


def test_refreshing_needs_sign_in(client: Client) -> None:
    response = client.post(reverse("investments_refresh_prices"))

    assert response["Location"].startswith(reverse("login"))
    assert not ProcrastinateJob.objects.exists()
