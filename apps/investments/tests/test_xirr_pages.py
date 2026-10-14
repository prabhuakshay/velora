from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import account_url, page_text
from apps.investments.models import Instrument
from apps.investments.tests.conftest import (
    add_price,
    holdings_text,
    make_broker,
    record_event,
)
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
STOCK = "INE000000002"


def a_year_of_ten_percent(client: Client) -> Account:
    """A fund bought a year ago that grew 10%, and a stock bought today."""
    today = timezone.localdate()
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=STOCK, name="Acme Ltd", kind="stock")
    broker = make_broker("Zerodha", opening="5000", opened=today - timedelta(400))
    record_event(
        client,
        broker,
        "buy",
        FUND,
        date=str(today - timedelta(365)),
        units="10",
        amount="1000",
    )
    record_event(
        client,
        broker,
        "buy",
        STOCK,
        date=str(today),
        units="1",
        amount="50",
    )
    add_price(FUND, today, "110")
    add_price(STOCK, today, "50")
    return broker


def overview_text(client: Client, **query: str) -> str:
    response = client.get(reverse("investments_overview"), query)
    assert response.status_code == 200
    return page_text(response.content.decode())


def test_the_overview_shows_each_holdings_xirr(signed_in: Client) -> None:
    a_year_of_ten_percent(signed_in)

    text = overview_text(signed_in)

    assert "Nifty Fund Zerodha 10 ₹100.0000 ₹1,000.00 ₹1,100.00 +₹100.00" in text
    assert "+10.00% +10.00%" in text
    # Bought today: under one day of history.
    assert "Acme Ltd Zerodha 1 ₹50.0000 ₹50.00 ₹50.00 ₹0.00 0.00% —" in text


def test_the_overview_shows_the_portfolios_xirr(signed_in: Client) -> None:
    a_year_of_ten_percent(signed_in)

    text = overview_text(signed_in)

    # 1,000 a year ago and 50 today grew to 1,150: 10% on the 1,000.
    assert "Realized Gain ₹0.00 XIRR +10.00%" in text


def test_holdings_sort_by_xirr_with_none_lowest(signed_in: Client) -> None:
    a_year_of_ten_percent(signed_in)

    ascending = overview_text(signed_in, sort="xirr").partition("Holdings")[2]
    descending = overview_text(signed_in, sort="-xirr").partition("Holdings")[2]

    assert ascending.index("Acme Ltd") < ascending.index("Nifty Fund")
    assert descending.index("Nifty Fund") < descending.index("Acme Ltd")


def test_the_holdings_tab_shows_the_account_and_each_holdings_xirr(
    signed_in: Client,
) -> None:
    broker = a_year_of_ten_percent(signed_in)

    text = holdings_text(signed_in, broker)

    assert "Realized Gain ₹0.00 XIRR +10.00%" in text
    today = f"{timezone.localdate():%-d %b %Y}"
    assert (
        f"Nifty Fund 10 ₹1,000.00 ₹1,100.00 +₹100.00 ₹0.00 ₹0.00 {today} +10.00%"
    ) in text
    assert f"Acme Ltd 1 ₹50.00 ₹50.00 ₹0.00 ₹0.00 ₹0.00 {today} —" in text


def test_the_account_page_shows_the_accounts_xirr(signed_in: Client) -> None:
    broker = a_year_of_ten_percent(signed_in)

    response = signed_in.get(account_url("account_transactions", broker))

    assert "XIRR +10.00%" in page_text(response.content.decode())


def test_privacy_mode_hides_xirr(signed_in: Client) -> None:
    broker = a_year_of_ten_percent(signed_in)
    turn_on(signed_in, reverse("index"))

    assert "10.00%" not in overview_text(signed_in)
    assert "10.00%" not in holdings_text(signed_in, broker)
