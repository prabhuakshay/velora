from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.net_worth import net_worth, net_worth_on
from apps.accounts.tests.conftest import account_url, edit_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_net_worth import home_text
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import (
    add_price,
    holdings_text,
    make_broker,
    record_event,
)
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

FUND = "INF000000010"


@pytest.fixture(autouse=True)
def _fund() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


def test_home_net_worth_counts_an_investment_account_at_market_value(
    signed_in: Client,
) -> None:
    opening("Bank", "asset", "500")
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")
    add_price(FUND, date(2026, 3, 5), "150")

    page = home_text(signed_in)

    # Bank 500, Cash 9000 and 10 units at 150.
    assert "Net Worth ₹11,000.00" in page


def test_an_excluded_investment_account_stays_out_of_net_worth(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")
    add_price(FUND, date(2026, 3, 5), "150")

    edit_account(signed_in, broker, include_in_net_worth=False)

    assert "Net Worth ₹0.00" in home_text(signed_in)


def test_past_net_worth_uses_the_events_and_prices_of_that_day() -> None:
    broker = make_broker(opening="10000")
    InvestmentEvent.objects.create(
        account=broker,
        instrument=Instrument.objects.get(isin=FUND),
        kind="buy",
        date=date(2026, 2, 10),
        units=10,
        amount=1000,
    )
    add_price(FUND, date(2026, 2, 27), "110")
    add_price(FUND, date(2026, 3, 31), "130")

    values = net_worth_on([date(2026, 1, 31), date(2026, 2, 28), date(2026, 4, 2)])

    assert values[date(2026, 1, 31)].total == 10000
    assert values[date(2026, 2, 28)].total == 10100
    assert values[date(2026, 4, 2)].total == 10300
    assert net_worth(date(2026, 4, 2)).total == 10300


def test_an_investment_account_with_events_cant_be_deleted(signed_in: Client) -> None:
    broker = make_broker()
    record_event(signed_in, broker, "buy", FUND, units="1", amount="10")

    response = signed_in.post(account_url("account_delete", broker), follow=True)

    assert "Investment Events" in page_text(response.content.decode())
    broker.refresh_from_db()


def test_merging_investment_accounts_is_refused(signed_in: Client) -> None:
    broker = make_broker("Zerodha")
    other = make_broker("Groww")

    response = signed_in.post(
        account_url("account_merge", broker), {"target": other.pk}
    )

    assert "Investment Accounts can&#x27;t be merged" in page_text(
        response.content.decode()
    )
    assert broker.investment_events.count() == 0
    broker.refresh_from_db()


def test_privacy_mode_masks_every_new_amount(signed_in: Client) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")
    turn_on(signed_in, reverse("index"))

    holdings = holdings_text(signed_in, broker)
    account = signed_in.get(
        account_url("account_transactions", broker)
    ).content.decode()

    assert "₹" not in holdings.replace("₹••••", "")
    assert "10 units" not in holdings
    assert "Cash ₹••••" in page_text(account)


def home_queries(client: Client) -> int:
    with CaptureQueriesContext(connection) as queries:
        client.get(reverse("index"))
    return len(queries)


def test_home_costs_the_same_queries_however_many_investment_accounts(
    signed_in: Client,
) -> None:
    def add_broker(name: str) -> None:
        broker = make_broker(name, opening="1000")
        record_event(signed_in, broker, "buy", FUND, units="1", amount="10")

    add_broker("One")
    one = home_queries(signed_in)
    add_broker("Two")
    add_broker("Three")

    assert home_queries(signed_in) == one
