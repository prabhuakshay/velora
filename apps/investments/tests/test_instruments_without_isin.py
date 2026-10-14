from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_net_worth import home_text
from apps.investments.models import Instrument, InvestmentEvent, PriceSource
from apps.investments.tests.conftest import (
    event_data,
    holdings_text,
    make_broker,
    record_event,
)

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

GOLD = "Gold 24K (per gram)"


def buy_gold(
    client: Client, broker: Account, kind: str = "gold", date: str = "2026-03-01"
) -> None:
    record_event(
        client,
        broker,
        "buy",
        "",
        units="10",
        amount="60000",
        instrument_name=GOLD,
        instrument_kind=kind,
        date=date,
    )


def test_a_buy_without_an_isin_creates_a_manual_instrument_counted_in_net_worth(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="100000")

    buy_gold(signed_in, broker)
    gold = Instrument.objects.get(name=GOLD)
    signed_in.post(
        reverse("instrument_add_price", args=[gold.pk]),
        {"date": "2026-03-05", "price": "7000"},
    )

    assert gold.isin is None
    assert gold.kind == Instrument.Kind.GOLD
    assert gold.price_source == PriceSource.MANUAL
    assert f"{GOLD} 10 ₹60,000.00" in holdings_text(signed_in, broker)
    # Cash 40000 and 10 grams at 7000.
    assert "Net Worth ₹1,10,000.00" in home_text(signed_in)


def test_a_second_buy_with_the_same_name_reuses_the_instrument(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="200000")

    buy_gold(signed_in, broker)
    buy_gold(signed_in, broker, kind="other")

    assert Instrument.objects.filter(name=GOLD).count() == 1
    assert f"{GOLD} 20 ₹1,20,000.00" in holdings_text(signed_in, broker)


@pytest.mark.parametrize("isin", ["TEJASNET", "INE010J01013"])
def test_a_filled_in_isin_that_is_not_a_real_isin_is_refused(
    signed_in: Client, isin: str
) -> None:
    broker = make_broker(opening="1000")

    response = record_event(
        signed_in,
        broker,
        "buy",
        isin,
        units="1",
        amount="10",
        instrument_name="Tejas Networks",
        expect=200,
    )

    assert (
        "This isn&#x27;t a valid ISIN. For an Instrument without one, leave the "
        "ISIN blank and enter its name." in page_text(response.content.decode())
    )
    assert not Instrument.objects.exists()


def test_every_event_kind_takes_an_instrument_without_an_isin(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="100000")
    dividends = make_account("Dividends", "income")
    buy_gold(signed_in, broker, date="2026-02-01")

    for day, kind, fields in (
        (2, "sell", {"units": "2", "amount": "14000"}),
        (3, "dividend", {"amount": "50", "income_account": str(dividends.pk)}),
        (4, "stock_split", {"units": "2"}),
        (5, "bonus", {"units": "4"}),
    ):
        response = signed_in.post(
            reverse("investment_event_create", args=[broker.pk]),
            event_data(kind, "", instrument_name=GOLD, date=f"2026-03-0{day}") | fields,
        )
        assert response.status_code == 302

    assert InvestmentEvent.objects.filter(instrument__name=GOLD).count() == 5
    # 10 grams, 2 sold, 8 split into 16, plus 4 free.
    assert f"{GOLD} 20" in holdings_text(signed_in, broker)


def test_a_merger_can_turn_units_into_an_instrument_without_an_isin(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="100000")
    buy_gold(signed_in, broker, date="2026-02-01")

    record_event(
        signed_in,
        broker,
        "merger",
        "",
        instrument_name=GOLD,
        new_instrument_name="Gold 22K (per gram)",
    )

    merged = Instrument.objects.get(name="Gold 22K (per gram)")
    assert merged.isin is None
    assert merged.price_source == PriceSource.MANUAL
    assert "Gold 22K (per gram) 10 ₹60,000.00" in holdings_text(signed_in, broker)


def test_a_merger_into_a_new_name_differing_only_in_case_is_refused(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="100000")

    response = record_event(
        signed_in,
        broker,
        "merger",
        "",
        expect=200,
        instrument_name="Silver bar",
        new_instrument_name="silver BAR",
    )

    assert "Pick a different Instrument to merge into." in response.content.decode()
    assert not Instrument.objects.exists()


def test_editing_an_event_without_an_isin_starts_from_the_names(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="100000")
    buy_gold(signed_in, broker, date="2026-02-01")
    record_event(
        signed_in,
        broker,
        "merger",
        "",
        instrument_name=GOLD,
        new_instrument_name="Gold 22K",
    )
    merger = InvestmentEvent.objects.get(kind="merger")

    form = signed_in.get(reverse("investment_event_edit", args=[merger.pk])).context[
        "form"
    ]

    assert form["isin"].value() is None
    assert form["instrument_name"].value() == GOLD
    assert form["new_instrument_name"].value() == "Gold 22K"
