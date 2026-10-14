import csv
import io
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import (
    holdings_text,
    import_line,
    import_preview,
    imported,
    make_broker,
    record_event,
)
from apps.investments.tests.test_investment_draft_editing import (
    drafts_text,
    edit_data,
    edit_url,
    text_of,
)
from apps.investments.tests.test_investment_drafts import bank, buy_draft, kuvera, post

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

__all__ = ["bank", "kuvera"]

FUND = "INF000000001"


@pytest.fixture(autouse=True)
def _fund() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


def exported_rows(client: Client) -> list[dict[str, str]]:
    response = client.get(reverse("investment_export"))
    return list(csv.DictReader(io.StringIO(response.content.decode())))


def test_a_buy_records_units_and_amount_and_shows_its_trade_price(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="5000")

    record_event(signed_in, broker, "buy", FUND, units="3", amount="1000")

    event = InvestmentEvent.objects.get()
    assert (event.units, event.amount) == (Decimal(3), Decimal(1000))
    assert "3 units at ₹333.3333" in holdings_text(signed_in, broker)


def test_a_sell_records_units_and_amount(signed_in: Client) -> None:
    broker = make_broker(opening="5000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")

    record_event(
        signed_in, broker, "sell", FUND, units="4", amount="450", date="2026-03-02"
    )

    assert "4 units at ₹112.5000" in holdings_text(signed_in, broker)


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"units": "10"}, "This field is required."),
        ({"amount": "1000"}, "This field is required."),
        ({"units": "10", "amount": "0"}, "A Buy or Sell needs units and an amount"),
        ({"units": "0", "amount": "1000"}, "A Buy or Sell needs units and an amount"),
    ],
)
def test_a_buy_without_units_or_amount_above_zero_is_refused(
    signed_in: Client, fields: dict[str, str], reason: str
) -> None:
    broker = make_broker(opening="5000")

    response = record_event(signed_in, broker, "buy", FUND, expect=200, **fields)

    assert reason in page_text(response.content.decode())
    assert not InvestmentEvent.objects.exists()


def test_the_event_form_has_no_price_field_and_shows_the_trade_price(
    signed_in: Client,
) -> None:
    broker = make_broker()

    response = signed_in.get(reverse("investment_event_create", args=[broker.pk]))

    html = response.content.decode()
    assert 'name="price"' not in html
    assert "Trade Price" in page_text(html)
    assert "The trade value before charges; or the Dividend paid." in html


def test_the_draft_form_has_no_price_field_and_shows_the_trade_price(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera)

    html = signed_in.get(edit_url(draft)).content.decode()

    assert 'name="price"' not in html
    assert "Trade Price" in page_text(html)


def test_a_draft_card_shows_its_trade_price(signed_in: Client, kuvera: Account) -> None:
    buy_draft(kuvera, units="3")

    assert "Buy Nifty Fund in Kuvera · 3 units at ₹333.3333" in drafts_text(signed_in)


def test_a_draft_without_an_amount_says_so_and_is_not_posted(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera, amount=None)

    assert "Buy Nifty Fund in Kuvera · Amount needed" in drafts_text(signed_in)
    post(signed_in, draft)
    assert "missing amount" in draft.posting_error
    assert not InvestmentEvent.objects.exists()


def test_a_draft_posts_with_units_and_amount(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera, amount=None)

    response = signed_in.post(
        edit_url(draft), edit_data(units="3", amount="1000", action="post")
    )

    assert response.status_code == 302, text_of(response.content.decode())
    event = InvestmentEvent.objects.get()
    assert (event.units, event.amount) == (Decimal(3), Decimal(1000))


def test_export_writes_the_trade_price(signed_in: Client) -> None:
    broker = make_broker(opening="5000")
    record_event(signed_in, broker, "buy", FUND, units="3", amount="1000")

    [row] = exported_rows(signed_in)

    assert (row["units"], row["price"], row["amount"]) == ("3", "333.3333", "1000")


def test_an_exported_file_re_imports_with_nothing_changed(signed_in: Client) -> None:
    broker = make_broker(opening="5000")
    record_event(signed_in, broker, "buy", FUND, units="3", amount="1000")
    text = signed_in.get(reverse("investment_export")).content.decode()

    page = import_preview(signed_in, *text.splitlines()[1:])

    assert "0 to add · 1 already recorded · 0 with errors" in page


def test_an_import_row_may_leave_the_price_blank(signed_in: Client) -> None:
    broker = make_broker(opening="5000")

    imported(signed_in, import_line("BUY", units="3", amount="1000"))

    assert "3 units at ₹333.3333" in holdings_text(signed_in, broker)


@pytest.mark.parametrize(
    ("units", "price", "amount"),
    [
        # A mutual fund Buy: NAV to 4 decimals, units rounded to 3.
        ("81.234", "12.3105", "1000"),
        # Just inside the ₹1 floor.
        ("10", "50.1", "500"),
        # Just inside 0.1% of the amount, which is above ₹1.
        ("100", "1001", "100000"),
        # The exported Trade Price, though rounding it drifts ₹49 over many units.
        ("1234567", "0.0049", "6000"),
    ],
)
def test_an_import_price_that_agrees_with_units_and_amount_is_accepted(
    signed_in: Client, units: str, price: str, amount: str
) -> None:
    make_broker(opening="200000")

    imported(signed_in, import_line("BUY", units=units, price=price, amount=amount))

    assert InvestmentEvent.objects.get().amount == Decimal(amount)


@pytest.mark.parametrize(
    ("units", "price", "amount", "trade_price"),
    [
        # Just outside the ₹1 floor.
        ("10", "50.1001", "500", "50.0000"),
        # Just outside 0.1% of the amount.
        ("100", "1001.0001", "100000", "1000.0000"),
    ],
)
def test_an_import_price_that_disagrees_with_units_and_amount_is_an_error(
    signed_in: Client, units: str, price: str, amount: str, trade_price: str
) -> None:
    make_broker(opening="200000")

    page = import_preview(
        signed_in, import_line("BUY", units=units, price=price, amount=amount)
    )

    assert "1 with errors" in page
    assert (
        f"price: Doesn&#x27;t agree with units and amount, which give {trade_price}."
        in page
    )
    assert "Confirm import" not in page
