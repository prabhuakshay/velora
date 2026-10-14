from datetime import date
from decimal import Decimal

import pytest

from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import add_price, make_broker
from apps.investments.valuation import Valuer

pytestmark = pytest.mark.django_db

FUND = "INF000000010"
ETF = "INF000000036"
OPENED = date(2026, 1, 2)


@pytest.fixture(autouse=True)
def _instruments() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=ETF, name="Gold ETF", kind="etf")


def event(account: int, kind: str, day: int, units: str, amount: str) -> None:
    InvestmentEvent.objects.create(
        account_id=account,
        instrument=Instrument.objects.get(isin=FUND),
        kind=kind,
        date=date(2026, 1, day),
        units=Decimal(units),
        amount=Decimal(amount),
    )


def test_cash_is_balance_less_cost_basis_plus_gains_after_the_opening_date() -> None:
    broker = make_broker(opened=OPENED).pk
    event(broker, "buy", 1, "10", "1000")
    event(
        broker, "sell", 2, "2", "260"
    )  # on the Opening Balance date: gain 60 inside it
    event(broker, "sell", 5, "3", "390")  # gain 90 after it

    cash = Valuer([broker]).cash(broker, OPENED, Decimal(2000), date(2026, 1, 31))

    # Balance 2000 less 500 still held, plus the later gain.
    assert cash == Decimal(1590)


def test_cash_without_events_is_the_balance() -> None:
    broker = make_broker().pk

    cash = Valuer([broker]).cash(broker, OPENED, Decimal(500), date(2026, 1, 31))

    assert cash == Decimal(500)


def test_market_value_is_cash_plus_units_at_their_price() -> None:
    broker = make_broker(opened=date(2026, 1, 1))
    event(broker.pk, "buy", 1, "3.5", "300")
    InvestmentEvent.objects.create(
        account=broker,
        instrument=Instrument.objects.get(isin=ETF),
        kind="buy",
        date=date(2026, 1, 1),
        units=Decimal(2),
        amount=Decimal(50),
    )
    add_price(FUND, date(2026, 1, 3), "120.1234")

    value = Valuer([broker.pk]).value(broker, Decimal(450))

    # Cash 100, 3.5 x 120.1234 = 420.43, plus 50 at cost for the unpriced one.
    assert value.cash == Decimal(100)
    assert value.market_value == Decimal("570.43")
    assert [row.instrument.name for row in value.holdings] == [
        "Gold ETF",
        "Nifty Fund",
    ]


def test_a_value_on_a_day_uses_the_latest_price_by_then_stale_against_it() -> None:
    broker = make_broker(opened=date(2026, 1, 1))
    event(broker.pk, "buy", 1, "10", "1000")
    old = add_price(FUND, date(2026, 1, 3), "110")
    add_price(FUND, date(2026, 1, 20), "130")

    value = Valuer([broker.pk]).value(broker, Decimal(1000), on=date(2026, 1, 10))

    assert value.holdings[0].price == old
    assert value.holdings[0].stale
    assert value.market_value == Decimal(1100)
