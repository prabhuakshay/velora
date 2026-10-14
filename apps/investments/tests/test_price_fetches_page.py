import re
from datetime import date, timedelta
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.investments.prices import PriceFetchError, fetch_today
from apps.investments.tests.conftest import row, unreachable
from apps.schedules.daily_job import run_daily_job
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.tests.conftest import FakePrices

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 14)


def fetch_rows(client: Client) -> list[str]:
    html = client.get(reverse("price_fetches")).content.decode()
    body = re.search(r"<tbody>(.*?)</tbody>", html, re.DOTALL)
    if not body:
        assert "No Price Fetches in the last 90 days" in html
        return []
    return [
        unescape(page_text(r))
        for r in re.findall(r"<tr.*?>(.*?)</tr>", body.group(1), re.DOTALL)
    ]


def test_the_page_lists_each_price_fetch_with_what_it_did(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [row("INF209KA12Z1", "A fund", "mutual_fund", "10", TODAY)]
    fake_prices.nse = unreachable()

    with pytest.raises(PriceFetchError):
        fetch_today(TODAY)

    nse, amfi = fetch_rows(signed_in)
    now = f"{timezone.localtime():%-d %b %Y}"
    assert now in amfi
    assert "Nightly AMFI Worked" in amfi
    assert "14 Oct 2026" in amfi
    assert amfi.endswith("1")
    assert "Nightly NSE Failed NSE couldn't be reached" in nse


def test_the_status_line_links_to_the_page(signed_in: Client) -> None:
    html = signed_in.get(reverse("investments_overview")).content.decode()

    assert f'href="{reverse("price_fetches")}"' in html


@pytest.mark.parametrize(("days_later", "kept"), [(90, 1), (91, 0)])
def test_the_daily_job_removes_price_fetches_older_than_90_days(
    signed_in: Client, fake_prices: FakePrices, days_later: int, kept: int
) -> None:
    fake_prices.amfi = []
    fake_prices.nse = []
    fetch_today(TODAY)

    run_daily_job(timezone.localdate() + timedelta(days=days_later))

    assert len(fetch_rows(signed_in)) == 2 * kept


def test_the_page_needs_sign_in(client: Client) -> None:
    response = client.get(reverse("price_fetches"))

    assert response["Location"].startswith(reverse("login"))


def test_privacy_mode_hides_how_many_prices_were_stored(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [row("INF209KA12Z1", "A fund", "mutual_fund", "10", TODAY)]
    fake_prices.nse = []
    fetch_today(TODAY)
    turn_on(signed_in)

    _, amfi = fetch_rows(signed_in)

    assert "Worked" in amfi
    assert not amfi.endswith("1")
