from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Account
from apps.accounts.tests.conftest import account_url, page_text
from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument, Price
from apps.investments.tests.conftest import (
    add_price,
    instrument_url,
    make_broker,
    record_event,
)
from apps.users.tests.conftest import turn_on
from apps.users.tests.test_number_format import use_format

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
SOLD = "INE000000002"
ETF = "INF000000003"


def three_holdings(client: Client) -> None:
    """A fund, a partly sold stock and an unpriced ETF in two accounts."""
    today = timezone.localdate()
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=SOLD, name="Acme Ltd", kind="stock")
    Instrument.objects.create(isin=ETF, name="Gold ETF", kind="etf")
    zerodha = make_broker("Zerodha", opening="10000")
    groww = make_broker("Groww", opening="500")
    record_event(client, zerodha, "buy", FUND, units="10", price="100", amount="1000")
    record_event(client, zerodha, "buy", SOLD, units="2", price="50", amount="100")
    record_event(client, zerodha, "sell", SOLD, units="1", price="60", amount="60")
    record_event(client, groww, "buy", ETF, units="5", price="20", amount="100")
    add_price(FUND, today, "150")
    add_price(SOLD, today, "40")


def overview(client: Client) -> str:
    response = client.get(reverse("investments_overview"))
    assert response.status_code == 200
    return response.content.decode()


def test_the_overview_lists_investment_accounts_and_instruments_held(
    signed_in: Client,
) -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=SOLD, name="Acme Ltd", kind="stock")
    opening("Bank", "asset", "100")
    broker = make_broker("Zerodha", opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", price="100", amount="1000")
    record_event(signed_in, broker, "buy", SOLD, units="1", price="50", amount="50")
    record_event(signed_in, broker, "sell", SOLD, units="1", price="60", amount="60")
    add_price(FUND, timezone.localdate(), "150")

    html = overview(signed_in)

    text = page_text(html)
    assert "Zerodha ₹10,510.00" in text
    assert "Nifty Fund Zerodha 10 ₹100.0000 ₹1,000.00 ₹1,500.00" in text
    assert "Bank" not in text
    assert "Acme Ltd" not in text
    assert f'href="{account_url("account_transactions", broker)}"' in html
    assert f'href="{instrument_url(FUND)}"' in html


def test_investments_is_marked_in_the_nav_on_instrument_pages(
    signed_in: Client,
) -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")

    body = signed_in.get(instrument_url(FUND)).content.decode()

    assert f'href="{reverse("investments_overview")}" aria-current="page"' in body


def test_the_overview_says_when_there_is_nothing_yet(signed_in: Client) -> None:
    assert "No Investment Accounts yet" in page_text(overview(signed_in))


def test_privacy_mode_masks_the_overview(signed_in: Client) -> None:
    three_holdings(signed_in)
    turn_on(signed_in, reverse("index"))

    html = overview(signed_in)

    text = page_text(html)
    assert "₹1" not in text
    assert "₹4" not in text
    assert "%" not in text.replace("••••%", "")
    assert "Nifty Fund Zerodha 10" not in text
    assert 'aria-label="Percentage hidden"' in html


def test_the_overview_follows_the_number_format(signed_in: Client, user: User) -> None:
    three_holdings(signed_in)
    Price.objects.filter(instrument__isin=FUND).update(price=15000)
    use_format(user, "international")

    text = page_text(overview(signed_in))

    assert "Market Value ₹150,140.00" in text
    assert "Nifty Fund Zerodha 10 ₹100.0000 ₹1,000.00 ₹150,000.00" in text


def test_the_overview_totals_every_holding_across_investment_accounts(
    signed_in: Client,
) -> None:
    three_holdings(signed_in)

    text = page_text(overview(signed_in))

    assert (
        "Invested ₹1,150.00 Market Value ₹1,640.00 "
        "Unrealized Gain +₹490.00 +42.61% Realized Gain +₹10.00"
    ) in text


def test_the_overview_splits_the_totals_by_mutual_funds_stocks_and_etfs(
    signed_in: Client,
) -> None:
    three_holdings(signed_in)

    text = page_text(overview(signed_in))

    assert (
        "Mutual funds ₹1,000.00 ₹1,500.00 +₹500.00 +50.00% ₹0.00 "
        "Stocks ₹50.00 ₹40.00 -₹10.00 -20.00% +₹10.00 "
        "ETFs ₹100.00 ₹100.00 ₹0.00 0.00% ₹0.00 "
        "Total ₹1,150.00 ₹1,640.00 +₹490.00 +42.61% +₹10.00"
    ) in text


def test_holdings_with_a_stale_price_are_flagged(signed_in: Client) -> None:
    three_holdings(signed_in)
    add_price(SOLD, timezone.localdate() - timedelta(days=6), "45")
    Price.objects.filter(instrument__isin=SOLD, date=timezone.localdate()).delete()

    text = page_text(overview(signed_in))

    assert "Acme Ltd Stale Zerodha" in text
    assert "Nifty Fund Zerodha" in text


def holdings_order(client: Client, sort: str = "") -> list[str]:
    response = client.get(reverse("investments_overview"), {"sort": sort})
    table = page_text(response.content.decode()).partition("Holdings")[2]
    names = ("Acme Ltd", "Gold ETF", "Nifty Fund")
    return sorted(names, key=table.index)


def test_the_holdings_table_shows_each_holding_with_its_account(
    signed_in: Client,
) -> None:
    three_holdings(signed_in)

    html = overview(signed_in)

    text = page_text(html)
    assert "Acme Ltd Zerodha 1 ₹50.0000 ₹50.00 ₹40.00 -₹10.00 -20.00%" in text
    assert "Gold ETF No Price yet Groww 5 ₹20.0000 ₹100.00 ₹100.00 ₹0.00 0.00%" in text
    assert "Nifty Fund Zerodha 10 ₹100.0000 ₹1,000.00 ₹1,500.00 +₹500.00" in text
    groww = Account.objects.get(name="Groww")
    assert f'href="{reverse("account_holdings", args=[groww.pk])}"' in html


@pytest.mark.parametrize(
    ("column", "ascending"),
    [
        ("instrument", ["Acme Ltd", "Gold ETF", "Nifty Fund"]),
        ("units", ["Acme Ltd", "Gold ETF", "Nifty Fund"]),
        ("average_cost", ["Gold ETF", "Acme Ltd", "Nifty Fund"]),
        ("invested", ["Acme Ltd", "Gold ETF", "Nifty Fund"]),
        ("market_value", ["Acme Ltd", "Gold ETF", "Nifty Fund"]),
        ("gain", ["Acme Ltd", "Gold ETF", "Nifty Fund"]),
    ],
)
def test_each_holdings_column_sorts_both_ways(
    signed_in: Client, column: str, ascending: list[str]
) -> None:
    three_holdings(signed_in)

    assert holdings_order(signed_in, column) == ascending
    assert holdings_order(signed_in, f"-{column}") == ascending[::-1]


def test_holdings_sort_by_investment_account_then_instrument(
    signed_in: Client,
) -> None:
    three_holdings(signed_in)

    assert holdings_order(signed_in, "account") == [
        "Gold ETF",
        "Acme Ltd",
        "Nifty Fund",
    ]
    assert holdings_order(signed_in, "-account") == [
        "Acme Ltd",
        "Nifty Fund",
        "Gold ETF",
    ]


def test_a_column_header_sorts_the_other_way_once_sorted_by_it(
    signed_in: Client,
) -> None:
    three_holdings(signed_in)

    response = signed_in.get(reverse("investments_overview"), {"sort": "units"})

    body = response.content.decode()
    assert 'aria-sort="ascending"' in body
    assert 'href="?sort=-units"' in body
    assert 'href="?sort=market_value"' in body


def test_an_unknown_sort_lists_holdings_by_instrument(signed_in: Client) -> None:
    three_holdings(signed_in)

    assert holdings_order(signed_in, "nonsense") == [
        "Acme Ltd",
        "Gold ETF",
        "Nifty Fund",
    ]
