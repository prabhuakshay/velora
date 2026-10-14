import re
from datetime import date, timedelta
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.tests.conftest import page_text
from apps.investments.prices import PriceFetchError, fetch_today
from apps.investments.tests.conftest import not_published, row

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.tests.conftest import FakePrices

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 14)
YESTERDAY = TODAY - timedelta(days=1)


def banners(client: Client) -> list[str]:
    """The text of each failed Price Fetch banner on the overview."""
    html = client.get(reverse("investments_overview")).content.decode()
    found = re.findall(r'<div data-fetch-failed="\w+".*?</div>', html, re.DOTALL)
    return [unescape(page_text(banner)) for banner in found]


def fetch(fake_prices: FakePrices, day: date, *, nse_fails: bool = False) -> None:
    fake_prices.amfi = [row("INF209KA12Z1", "A fund", "mutual_fund", "10", day)]
    if nse_fails:
        fake_prices.nse = not_published()
        with pytest.raises(PriceFetchError):
            fetch_today(day)
    else:
        fake_prices.nse = [row("INE002A01018", "Reliance", "stock", "2950", day)]
        fetch_today(day)


def test_a_failed_fetch_shows_a_banner_with_its_reason_and_the_day_shown(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fetch(fake_prices, YESTERDAY)
    fetch(fake_prices, TODAY, nse_fails=True)

    [banner] = banners(signed_in)
    assert "NSE Price Fetch failed: NSE has no file for 14 Oct" in banner
    assert "Showing NSE Prices for 13 Oct 2026" in banner


def test_the_banner_is_gone_once_a_later_fetch_works(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fetch(fake_prices, YESTERDAY, nse_fails=True)
    fetch(fake_prices, TODAY)

    assert banners(signed_in) == []


def test_no_banner_shows_when_every_fetch_worked(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fetch(fake_prices, TODAY)

    assert banners(signed_in) == []


def test_retry_queues_a_refresh(signed_in: Client, fake_prices: FakePrices) -> None:
    fetch(fake_prices, TODAY, nse_fails=True)
    html = signed_in.get(reverse("investments_overview")).content.decode()
    banner = re.search(r'<div data-fetch-failed="NSE".*?</div>', html, re.DOTALL)
    assert banner
    retry = re.search(
        r'<form method="post" action="([^"]+)">.*?Retry', banner.group(0), re.DOTALL
    )
    assert retry

    response = signed_in.post(retry.group(1), follow=True)

    assert "Refreshing Prices" in response.content.decode()
    assert ProcrastinateJob.objects.get().task_name == "investments.refresh_prices"
