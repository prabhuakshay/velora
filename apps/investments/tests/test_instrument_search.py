from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account, page_text
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import event_data, make_broker

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

RELIANCE = "INE002A01018"
TEJAS = "INE010J01012"
GOLD = "Gold 24K (per gram)"


def search(client: Client, query: str) -> str:
    response = client.get(reverse("instrument_search"), {"q": query})
    assert response.status_code == 200
    return page_text(response.content.decode())


def known() -> None:
    Instrument.objects.create(isin=RELIANCE, name="Reliance Industries", kind="stock")
    Instrument.objects.create(isin=TEJAS, name="Tejas Networks", kind="stock")
    Instrument.objects.create(name=GOLD, kind=Instrument.Kind.GOLD)


def post_event(
    client: Client, account: Account, kind: str, **fields: str
) -> tuple[int, str]:
    response = client.post(
        reverse("investment_event_create", args=[account.pk]),
        event_data(kind, fields.pop("isin", ""), **fields),
    )
    return response.status_code, unescape(page_text(response.content.decode()))


def buy(client: Client, broker: Account, **fields: str) -> tuple[int, str]:
    return post_event(client, broker, "buy", units="10", amount="1000", **fields)


def test_search_finds_instruments_by_name_and_isin_prefix_ignoring_case(
    signed_in: Client,
) -> None:
    known()

    by_name = search(signed_in, "tejas")
    by_isin = search(signed_in, RELIANCE[:6].lower())
    no_isin = search(signed_in, "GOLD")

    assert "Tejas Networks" in by_name
    assert "Reliance" not in by_name
    assert "Reliance Industries" in by_isin
    assert "Tejas" not in by_isin
    assert GOLD in no_isin


def test_search_shows_at_most_ten_instruments(signed_in: Client) -> None:
    for n in range(12):
        Instrument.objects.create(name=f"Fund {n:02}")

    text = search(signed_in, "fund")

    assert "Fund 09" in text
    assert "Fund 10" not in text


def test_search_needs_signing_in(client: Client) -> None:
    response = client.get(reverse("instrument_search"), {"q": "x"})

    assert response.status_code == 302


def test_a_chosen_instrument_records_the_event_on_it(signed_in: Client) -> None:
    known()
    broker = make_broker(opening="10000")

    status, _ = buy(signed_in, broker, instrument=TEJAS)
    gold_status, _ = buy(signed_in, broker, instrument=GOLD)

    assert (status, gold_status) == (302, 302)
    assert InvestmentEvent.objects.get(instrument__isin=TEJAS).units == 10
    assert InvestmentEvent.objects.filter(instrument__name=GOLD).count() == 1
    assert Instrument.objects.count() == 3


def test_a_pasted_full_isin_matches_the_known_instrument(signed_in: Client) -> None:
    known()
    broker = make_broker(opening="10000")

    status, _ = buy(signed_in, broker, instrument=f" {TEJAS.lower()} ")

    assert status == 302
    assert InvestmentEvent.objects.get().instrument.name == "Tejas Networks"


def test_an_instrument_nothing_matches_is_refused(signed_in: Client) -> None:
    known()
    broker = make_broker(opening="10000")

    status, text = buy(signed_in, broker, instrument="Tejas")

    assert status == 200
    assert "No Instrument matches this" in text
    assert not InvestmentEvent.objects.exists()


def test_add_new_creates_the_instrument_with_the_event(signed_in: Client) -> None:
    broker = make_broker(opening="10000")

    status, _ = buy(
        signed_in,
        broker,
        add_new="on",
        instrument_name="Tata Steel SGB",
        instrument_kind="bond",
        isin="INF209KA12Z1",
    )

    assert status == 302
    added = InvestmentEvent.objects.get().instrument
    assert (added.name, added.kind, added.isin) == (
        "Tata Steel SGB",
        "bond",
        "INF209KA12Z1",
    )


def test_add_new_with_a_name_already_used_without_an_isin_is_refused_in_any_case(
    signed_in: Client,
) -> None:
    known()
    broker = make_broker(opening="10000")

    status, text = buy(signed_in, broker, add_new="on", instrument_name=GOLD.upper())

    assert status == 200
    assert "There's already an Instrument without an ISIN named this" in text
    assert not InvestmentEvent.objects.exists()


def test_add_new_with_a_known_isin_uses_that_instrument(signed_in: Client) -> None:
    known()
    broker = make_broker(opening="10000")

    status, _ = buy(
        signed_in, broker, add_new="on", instrument_name="Tejas Net", isin=TEJAS
    )

    assert status == 302
    assert InvestmentEvent.objects.get().instrument.name == "Tejas Networks"
    assert Instrument.objects.count() == 3


def test_add_new_checks_the_isin(signed_in: Client) -> None:
    broker = make_broker(opening="10000")

    status, text = buy(
        signed_in, broker, add_new="on", instrument_name="Tejas", isin="INE010J01013"
    )

    assert status == 200
    assert "This isn't a valid ISIN" in text
    assert not Instrument.objects.exists()


def test_add_new_needs_a_name(signed_in: Client) -> None:
    broker = make_broker(opening="10000")

    status, text = buy(signed_in, broker, add_new="on", isin=TEJAS)

    assert status == 200
    assert "Enter the new Instrument's name." in text


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        ("sell", {"units": "2", "amount": "300"}),
        ("dividend", {"amount": "50"}),
        ("stock_split", {"units": "2"}),
        ("bonus", {"units": "4"}),
    ],
)
def test_every_event_kind_takes_the_instrument_field(
    signed_in: Client, kind: str, fields: dict[str, str]
) -> None:
    known()
    broker = make_broker(opening="10000")
    buy(signed_in, broker, instrument=TEJAS)
    if kind == "dividend":
        fields |= {"income_account": str(make_account("Dividends", "income").pk)}

    status, _ = post_event(
        signed_in, broker, kind, instrument=TEJAS, date="2026-03-02", **fields
    )

    assert status == 302
    assert InvestmentEvent.objects.filter(instrument__isin=TEJAS, kind=kind).exists()


def test_a_merger_picks_its_new_instrument_with_the_same_field(
    signed_in: Client,
) -> None:
    known()
    broker = make_broker(opening="10000")
    buy(signed_in, broker, instrument=TEJAS)

    status, _ = post_event(
        signed_in, broker, "merger", instrument=TEJAS, new_instrument=RELIANCE
    )

    assert status == 302
    assert InvestmentEvent.objects.filter(
        kind="merger", new_instrument__isin=RELIANCE
    ).exists()


def test_a_mergers_new_instrument_can_be_added(signed_in: Client) -> None:
    known()
    broker = make_broker(opening="10000")
    buy(signed_in, broker, instrument=TEJAS)

    status, _ = post_event(
        signed_in,
        broker,
        "merger",
        instrument=TEJAS,
        new_add_new="on",
        new_instrument_name="Tejas Holdings",
    )
    refused, text = post_event(
        signed_in,
        broker,
        "merger",
        instrument=TEJAS,
        new_add_new="on",
        new_instrument_name=GOLD,
        date="2026-03-02",
    )

    assert status == 302
    merged = Instrument.objects.get(merged_into_events__kind="merger")
    assert (merged.name, merged.isin, merged.kind) == ("Tejas Holdings", None, "stock")
    assert refused == 200
    assert "There's already an Instrument without an ISIN named this" in text


def test_the_form_shows_the_search_field(signed_in: Client) -> None:
    broker = make_broker()

    response = signed_in.get(reverse("investment_event_create", args=[broker.pk]))

    html = response.content.decode()
    assert f'data-instrument-search="{reverse("instrument_search")}"' in html
    assert "js/instrument_search.js" in html
