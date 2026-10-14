from datetime import timedelta
from email.message import Message
from typing import TYPE_CHECKING
from urllib.error import HTTPError

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils import timezone

from apps.investments.nightly import PriceFetchError, run_nightly_prices
from apps.investments.tests.conftest import FakePriceSource, row
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from pytest_django import Settings

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("user")]

SITE = "https://velora.example"


@pytest.fixture(autouse=True)
def _site(settings: Settings) -> None:
    settings.SITE_URL = SITE


def not_published() -> HTTPError:
    return HTTPError("https://nse.example/file.zip", 404, "Not Found", Message(), None)


def test_a_failed_nightly_price_fetch_is_in_the_digest(
    fake_prices: FakePriceSource,
) -> None:
    today = timezone.localdate()
    fake_prices.nse = not_published()
    with pytest.raises(PriceFetchError):
        run_nightly_prices(today)

    run_daily_job(today + timedelta(days=1))

    [email] = mail.outbox
    assert "Price Fetches" in email.body
    assert f"NSE Price Fetch failed: NSE has no file for {today:%-d %b}" in email.body
    assert SITE + reverse("investments_overview") in email.body
    assert "AMFI Price Fetch failed" not in email.body
    assert "₹?" not in email.body
    assert isinstance(email, EmailMultiAlternatives)
    [(html, _)] = email.alternatives
    assert isinstance(html, str)
    assert f"NSE Price Fetch failed: NSE has no file for {today:%-d %b}" in html
    assert "₹?" not in html


def test_the_digest_is_silent_when_every_price_fetch_worked(
    fake_prices: FakePriceSource,
) -> None:
    today = timezone.localdate()
    fake_prices.nse = [row("INE002A01018", "Reliance", "stock", "2950", today)]
    run_nightly_prices(today)

    run_daily_job(today + timedelta(days=1))

    assert all("Price Fetch" not in str(email.body) for email in mail.outbox)


def test_a_later_nightly_price_fetch_that_worked_clears_the_line(
    fake_prices: FakePriceSource,
) -> None:
    today = timezone.localdate()
    fake_prices.nse = not_published()
    with pytest.raises(PriceFetchError):
        run_nightly_prices(today - timedelta(days=1))
    fake_prices.nse = [row("INE002A01018", "Reliance", "stock", "2950", today)]
    run_nightly_prices(today)

    run_daily_job(today + timedelta(days=1))

    assert all("Price Fetch" not in str(email.body) for email in mail.outbox)
