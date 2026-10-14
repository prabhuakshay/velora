from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone

from apps.investments.models import Instrument, Price, PriceFetch
from apps.investments.prices import PriceFetchError, fetch_today
from apps.investments.tests.conftest import (
    FakePrices,
    instrument_page,
    row,
    unreachable,
)

if TYPE_CHECKING:
    from datetime import date

    from django.test import Client

    from apps.investments.price_source import PriceRow

pytestmark = pytest.mark.django_db

FUND = "INF209KA12Z1"
STOCK = "INE002A01018"


def fund(price: str, day: date) -> PriceRow:
    return row(FUND, "ABSL Banking PSU Debt - Direct", "mutual_fund", price, day)


def test_the_nightly_job_creates_instruments_with_their_price(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    fake_prices.amfi = [fund("101.4192", today)]
    fake_prices.nse = [
        row("INE002A01018", "Reliance Industries", "stock", "2950.15", today),
        row("INF204KB14I2", "Nippon India Nifty BeES", "etf", "271.3", today),
    ]

    fetch_today(today)

    page = instrument_page(signed_in, FUND)
    assert "ABSL Banking PSU Debt - Direct" in page
    assert FUND in page
    assert "Mutual fund" in page
    assert f"₹101.4192 on {today:%-d %b %Y}" in page
    assert "Stock" in instrument_page(signed_in, "INE002A01018")
    assert "ETF" in instrument_page(signed_in, "INF204KB14I2")


def test_the_nightly_job_creates_and_prices_a_sovereign_gold_bond(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    fake_prices.nse = [
        row("IN0020230085", "SGB 2023-24 SR-III", "bond", "6150", today),
    ]

    fetch_today(today)

    page = instrument_page(signed_in, "IN0020230085")
    assert "SGB 2023-24 SR-III" in page
    assert "Bond" in page
    assert f"₹6,150.0000 on {today:%-d %b %Y}" in page


def test_running_twice_on_the_same_day_adds_nothing(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    fake_prices.amfi = [fund("101.4192", today)]
    fetch_today(today)

    fake_prices.amfi = [fund("999", today)]
    fetch_today(today)

    assert Instrument.objects.count() == 1
    assert Price.objects.count() == 1
    assert "₹101.4192" in instrument_page(signed_in, FUND)


def test_a_new_day_adds_a_price_and_keeps_the_instrument(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    fake_prices.amfi = [fund("100", today - timedelta(days=1))]
    fetch_today(today - timedelta(days=1))

    fake_prices.amfi = [fund("102.5", today)]
    fetch_today(today)

    assert Instrument.objects.count() == 1
    assert f"₹102.5000 on {today:%-d %b %Y}" in instrument_page(signed_in, FUND)


def test_a_failed_fetch_keeps_the_last_prices_and_runs_the_other_source(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    fake_prices.amfi = [fund("100", yesterday)]
    fetch_today(yesterday)

    fake_prices.amfi = unreachable()
    fake_prices.nse = [row(STOCK, "Reliance Industries", "stock", "2950", today)]
    with pytest.raises(PriceFetchError, match="AMFI"):
        fetch_today(today)

    page = instrument_page(signed_in, FUND)
    assert "ABSL Banking PSU Debt - Direct" in page
    assert f"₹100.0000 on {yesterday:%-d %b %Y}" in page
    assert "₹2,950.0000" in instrument_page(signed_in, STOCK)


def test_a_price_more_than_five_days_old_is_stale(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    fake_prices.amfi = [fund("100", today - timedelta(days=5))]
    fetch_today(today)
    assert "Stale" not in instrument_page(signed_in, FUND)

    Price.objects.update(date=today - timedelta(days=6))

    assert "Stale" in instrument_page(signed_in, FUND)


def test_the_job_leaves_an_instrument_without_an_isin_alone(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    today = timezone.localdate()
    gold = Instrument.objects.create(isin=None, name="My fund", kind="mutual_fund")
    fake_prices.amfi = [fund("101", today)]

    fetch_today(today)

    assert not gold.prices.exists()
    assert Instrument.objects.get(isin=FUND).prices.exists()


def test_a_fund_isin_priced_from_nse_gets_no_price_from_amfi(
    fake_prices: FakePrices,
) -> None:
    today = timezone.localdate()
    other = Instrument.objects.create(isin=FUND, name="Unlisted fund", kind="other")
    fake_prices.amfi = [fund("101", today)]

    fetch_today(today)

    assert not other.prices.exists()
    assert PriceFetch.objects.get(source="AMFI").prices_stored == 0
