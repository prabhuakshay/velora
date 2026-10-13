from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import add_price, make_broker
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
TODAY = date(2026, 4, 2)


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


def buy(account: Account, on: date, units: int, amount: int) -> None:
    InvestmentEvent.objects.create(
        account=account,
        instrument=Instrument.objects.get(isin=FUND),
        kind="buy",
        date=on,
        units=units,
        price=amount / units,
        amount=amount,
    )


def overview_html(client: Client) -> str:
    response = client.get(reverse("investments_overview"))
    assert response.status_code == 200
    return response.content.decode()


def value_history(client: Client) -> str:
    html = overview_html(client)
    table = html.split("<caption>Market Value and Invested", 1)[1]
    return page_text(table.split("</table>", 1)[0])


def test_the_overview_charts_market_value_and_invested_at_each_month_end(
    signed_in: Client,
) -> None:
    opening("Bank", "asset", "500")
    broker = make_broker("Zerodha", opening="10000")
    buy(broker, date(2026, 2, 10), units=10, amount=1000)
    add_price(FUND, date(2026, 2, 27), "110")
    add_price(FUND, date(2026, 3, 31), "130")

    history = value_history(signed_in)

    assert (
        "31 Jan 2026₹10,000.00₹0.00 "
        "28 Feb 2026₹10,100.00₹1,000.00 "
        "31 Mar 2026₹10,300.00₹1,000.00 "
        "2 Apr 2026₹10,300.00₹1,000.00"
    ) in history
    assert "<polyline" in overview_html(signed_in)


def test_the_chart_adds_up_every_investment_account(signed_in: Client) -> None:
    make_broker("Zerodha", opening="1000", opened=date(2026, 3, 1))
    groww = make_broker("Groww", opening="500", opened=date(2026, 3, 1))
    groww.include_in_net_worth = False
    groww.save()
    buy(groww, date(2026, 3, 2), units=2, amount=200)
    add_price(FUND, date(2026, 3, 2), "150")

    assert "31 Mar 2026₹1,600.00₹200.00 2 Apr 2026₹1,600.00₹200.00" in (
        value_history(signed_in)
    )


def test_privacy_mode_hides_the_value_chart(signed_in: Client) -> None:
    make_broker("Zerodha", opening="1000")
    turn_on(signed_in)

    html = overview_html(signed_in)

    assert "<polyline" not in html
    assert "Market Value and Invested at" not in html


def test_no_chart_without_investment_accounts(signed_in: Client) -> None:
    opening("Bank", "asset", "500")

    assert "<polyline" not in overview_html(signed_in)
