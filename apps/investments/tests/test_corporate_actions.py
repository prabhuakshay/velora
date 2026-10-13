from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.accounts.tests.test_net_worth import home_text
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import (
    add_price,
    event_data,
    holdings_text,
    make_broker,
    record_event,
)
from apps.investments.tests.test_investment_events import account_text

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

OLD = "INF000000001"
NEW = "INF000000002"


@pytest.fixture(autouse=True)
def _instruments() -> None:
    Instrument.objects.create(isin=OLD, name="Old Fund", kind="mutual_fund")
    Instrument.objects.create(isin=NEW, name="New Fund", kind="mutual_fund")


@pytest.fixture
def broker(signed_in: Client) -> Account:
    broker = make_broker(opening="10000")
    record_event(
        signed_in,
        broker,
        "buy",
        OLD,
        units="10",
        price="100",
        amount="1000",
        date="2026-02-01",
    )
    return broker


def test_a_stock_split_multiplies_units_and_keeps_cost_basis(
    signed_in: Client, broker: Account
) -> None:
    record_event(signed_in, broker, "stock_split", OLD, units="5", date="2026-02-10")

    holdings = holdings_text(signed_in, broker)
    assert "Old Fund 50 ₹1,000.00" in holdings
    assert "1 unit became 5" in holdings


def test_a_bonus_adds_units_at_no_cost(signed_in: Client, broker: Account) -> None:
    record_event(signed_in, broker, "bonus", OLD, units="2", date="2026-02-10")

    holdings = holdings_text(signed_in, broker)
    assert "Old Fund 12 ₹1,000.00" in holdings
    assert "2 free units" in holdings
    assert "Cash ₹9,000.00" in account_text(signed_in, broker)


def test_a_merger_moves_lots_to_the_new_instrument_keeping_cost_basis(
    signed_in: Client, broker: Account
) -> None:
    add_price(NEW, date(2026, 3, 1), "110")

    record_event(signed_in, broker, "merger", OLD, new_isin=NEW, date="2026-02-10")

    holdings = holdings_text(signed_in, broker)
    assert "New Fund 10 ₹1,000.00 ₹1,100.00 +₹100.00" in holdings
    assert "Old Fund 0 ₹0.00" in holdings
    assert "into New Fund" in holdings


def test_net_worth_values_merged_lots_at_the_new_instruments_price(
    signed_in: Client, broker: Account
) -> None:
    add_price(NEW, date(2026, 3, 1), "110")

    record_event(signed_in, broker, "merger", OLD, new_isin=NEW, date="2026-02-10")

    # Cash 9000 and 10 units at 110.
    assert "Net Worth ₹10,100.00" in home_text(signed_in)


def test_after_a_merger_the_old_instrument_cant_be_sold(
    signed_in: Client, broker: Account
) -> None:
    record_event(signed_in, broker, "merger", OLD, new_isin=NEW, date="2026-02-10")

    response = record_event(
        signed_in,
        broker,
        "sell",
        OLD,
        units="1",
        price="100",
        amount="100",
        date="2026-02-11",
        expect=200,
    )

    assert "Only 0 units of Old Fund were held on 11 Feb 2026." in page_text(
        response.content.decode()
    )


def test_a_merger_needs_a_known_and_different_new_isin(
    signed_in: Client, broker: Account
) -> None:
    unknown = record_event(
        signed_in, broker, "merger", OLD, new_isin="INF999999999", expect=200
    )
    same = record_event(signed_in, broker, "merger", OLD, new_isin=OLD, expect=200)

    assert unknown.context["form"].errors == {
        "new_isin": ["Velora doesn't know this ISIN."]
    }
    assert same.context["form"].errors == {
        "new_isin": ["Pick a different Instrument to merge into."]
    }


def test_editing_a_merger_starts_from_its_new_isin(
    signed_in: Client, broker: Account
) -> None:
    record_event(signed_in, broker, "merger", OLD, new_isin=NEW, date="2026-02-10")
    merger = InvestmentEvent.objects.get(kind="merger")

    response = signed_in.get(reverse("investment_event_edit", args=[merger.pk]))

    assert response.context["form"]["new_isin"].value() == NEW


def test_editing_a_stock_split_recomputes_lots(
    signed_in: Client, broker: Account
) -> None:
    record_event(signed_in, broker, "stock_split", OLD, units="5", date="2026-02-10")
    split = InvestmentEvent.objects.get(kind="stock_split")

    response = signed_in.post(
        reverse("investment_event_edit", args=[split.pk]),
        event_data("stock_split", OLD, units="2", date="2026-02-10"),
    )

    assert response.status_code == 302
    assert "Old Fund 20 ₹1,000.00" in holdings_text(signed_in, broker)


def test_deleting_a_bonus_a_later_sell_needs_is_refused(
    signed_in: Client, broker: Account
) -> None:
    record_event(signed_in, broker, "bonus", OLD, units="2", date="2026-02-10")
    record_event(
        signed_in,
        broker,
        "sell",
        OLD,
        units="12",
        price="100",
        amount="1200",
        date="2026-02-11",
    )
    bonus = InvestmentEvent.objects.get(kind="bonus")

    signed_in.post(reverse("investment_event_delete", args=[bonus.pk]))

    assert InvestmentEvent.objects.filter(pk=bonus.pk).exists()
