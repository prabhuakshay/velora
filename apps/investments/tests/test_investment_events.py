from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, page_text
from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument, InvestmentEvent, PriceSource
from apps.investments.tests.conftest import (
    add_price,
    event_data,
    holdings_text,
    make_broker,
    record_event,
)

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
STOCK = "INE000000002"


@pytest.fixture(autouse=True)
def _instruments() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=STOCK, name="Acme Ltd", kind="stock")


def account_text(client: Client, account: object) -> str:
    response = client.get(account_url("account_transactions", account))  # type: ignore[arg-type]
    return page_text(response.content.decode())


def test_a_buy_moves_cash_into_a_lot_and_leaves_the_balance(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="10000")

    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1000",
        charges="15",
    )

    page = account_text(signed_in, broker)
    assert "Balance ₹10,000.00" in page
    assert "Cash ₹8,985.00" in page
    assert "No Transactions yet" in page
    holdings = holdings_text(signed_in, broker)
    assert "Nifty Fund 10 ₹1,015.00" in holdings


def test_market_value_counts_units_at_the_latest_price(signed_in: Client) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")
    add_price(FUND, date(2026, 2, 1), "90")
    add_price(FUND, date(2026, 3, 2), "120.5")

    holdings = holdings_text(signed_in, broker)

    assert "Market Value ₹10,205.00" in holdings
    assert (
        "Nifty Fund 10 ₹1,000.00 ₹1,205.00 +₹205.00 ₹0.00 ₹0.00 "
        "₹120.5000 · 2 Mar 2026 · AMFI" in holdings
    )


def test_a_holding_without_a_price_counts_at_its_cost_basis(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="5000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")

    assert "Market Value ₹5,000.00" in holdings_text(signed_in, broker)


def test_a_sell_takes_the_oldest_lots_first_and_shows_its_realized_gain(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="10000")
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1000",
        date="2026-02-01",
    )
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1500",
        date="2026-02-02",
    )

    record_event(
        signed_in,
        broker,
        "sell",
        FUND,
        units="15",
        amount="2400",
        charges="10",
        date="2026-02-03",
    )

    holdings = holdings_text(signed_in, broker)
    assert "Nifty Fund 5 ₹750.00" in holdings
    assert "Realized Gain +₹640.00" in holdings
    # 10000 - 2500 bought + 2390 sold.
    assert "Cash ₹9,890.00" in account_text(signed_in, broker)


def test_a_sell_of_more_units_than_held_on_its_date_is_refused(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="10000")
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="3.5",
        amount="350",
        date="2026-02-01",
    )
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1000",
        date="2026-03-01",
    )

    response = record_event(
        signed_in,
        broker,
        "sell",
        FUND,
        units="4",
        amount="400",
        date="2026-02-15",
        expect=200,
    )

    assert "Only 3.5 units of Nifty Fund were held on 15 Feb 2026." in page_text(
        response.content.decode()
    )
    assert InvestmentEvent.objects.filter(kind="sell").count() == 0


def test_a_buy_with_an_unknown_isin_creates_an_instrument_priced_by_its_source(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="1000")

    record_event(
        signed_in,
        broker,
        "buy",
        "INE999999999",
        units="1",
        amount="10",
        instrument_name="Unlisted Co",
    )

    instrument = Instrument.objects.get(isin="INE999999999")
    assert instrument.name == "Unlisted Co"
    assert instrument.price_source == PriceSource.NSE
    assert "Unlisted Co 1 ₹10.00" in holdings_text(signed_in, broker)


def test_an_unknown_isin_needs_an_instrument_name(signed_in: Client) -> None:
    broker = make_broker(opening="1000")

    response = record_event(
        signed_in,
        broker,
        "buy",
        "INE999999999",
        units="1",
        amount="10",
        expect=200,
    )

    assert "Velora doesn&#x27;t know this ISIN; enter the Instrument&#x27;s name." in (
        page_text(response.content.decode())
    )
    assert not Instrument.objects.filter(isin="INE999999999").exists()


def test_editing_a_past_buy_recomputes_lots_cash_and_gains(signed_in: Client) -> None:
    broker = make_broker(opening="10000")
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1000",
        date="2026-02-01",
    )
    record_event(
        signed_in,
        broker,
        "sell",
        FUND,
        units="5",
        amount="600",
        date="2026-02-05",
    )
    first = InvestmentEvent.objects.get(kind="buy")

    response = signed_in.post(
        reverse("investment_event_edit", args=[first.pk]),
        event_data("buy", FUND, units="10", amount="800", date="2026-02-01"),
    )

    assert response.status_code == 302
    holdings = holdings_text(signed_in, broker)
    assert "Nifty Fund 5 ₹400.00" in holdings
    assert "Realized Gain +₹200.00" in holdings
    assert "Cash ₹9,800.00" in account_text(signed_in, broker)


def test_deleting_a_past_buy_recomputes_lots_and_cash(signed_in: Client) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")
    record_event(signed_in, broker, "buy", STOCK, units="2", amount="100")
    fund_buy = InvestmentEvent.objects.get(instrument__isin=FUND)

    response = signed_in.post(reverse("investment_event_delete", args=[fund_buy.pk]))

    assert response.status_code == 302
    holdings = holdings_text(signed_in, broker)
    assert "Nifty Fund" not in holdings
    assert "Cash ₹9,900.00" in account_text(signed_in, broker)


def test_deleting_a_buy_a_later_sell_needs_is_refused(signed_in: Client) -> None:
    broker = make_broker(opening="10000")
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1000",
        date="2026-02-01",
    )
    record_event(
        signed_in,
        broker,
        "sell",
        FUND,
        units="5",
        amount="600",
        date="2026-02-05",
    )
    buy = InvestmentEvent.objects.get(kind="buy")

    response = signed_in.post(
        reverse("investment_event_delete", args=[buy.pk]), follow=True
    )

    assert (
        "Can&#x27;t delete it: Only 0 units of Nifty Fund were held on 5 Feb 2026."
        in (page_text(response.content.decode()))
    )
    assert InvestmentEvent.objects.filter(pk=buy.pk).exists()


def test_events_on_or_before_the_opening_date_change_lots_not_cash(
    signed_in: Client,
) -> None:
    # The Opening Balance holds 2000 Cash and the 1000 Cost Basis held then.
    broker = make_broker(opening="3000", opened=date(2026, 2, 1))
    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="10",
        amount="1000",
        date="2025-06-01",
    )
    record_event(
        signed_in,
        broker,
        "sell",
        FUND,
        units="2",
        amount="220",
        date="2026-02-01",
    )
    # Cost 800 still held and the earlier gain is already inside the 3000.
    assert "Cash ₹2,200.00" in account_text(signed_in, broker)

    record_event(
        signed_in,
        broker,
        "sell",
        FUND,
        units="2",
        amount="260",
        date="2026-02-10",
    )

    assert "Cash ₹2,460.00" in account_text(signed_in, broker)


def test_a_future_dated_event_is_refused(signed_in: Client) -> None:
    broker = make_broker(opening="1000")

    response = record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="1",
        amount="10",
        date="2099-01-01",
        expect=200,
    )

    assert "Pick today or earlier." in page_text(response.content.decode())


def test_only_investment_accounts_have_holdings(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "100")

    response = signed_in.get(reverse("account_holdings", args=[bank.pk]))

    assert response.status_code == 404
