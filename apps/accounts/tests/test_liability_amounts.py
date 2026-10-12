from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import list_page, make_account, page_text
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.quick_add.tests.conftest import make_manual_draft

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db

PAID = '<span class="text-emerald-600">-₹10,000.00</span>'
CHARGED = "<span>+₹2,000.00</span>"


def card_in_credit() -> Account:
    """A card owing ₹3,000, charged ₹2,000, then paid ₹10,000: ₹5,000 in credit."""
    card = opening("Card", "liability", "3000")
    bank = opening("Bank", "asset", "50000")
    rent = make_account("Rent", "expense")
    today = timezone.localdate()
    record(today, card, rent, "2000", "Rent")
    record(today, bank, card, "10000", "Payment")
    return card


def test_card_page_reads_payments_and_charges_as_owed(signed_in: Client) -> None:
    page = view_page(signed_in, card_in_credit())

    text = page_text(page)
    assert PAID in page
    assert CHARGED in page
    assert "Paid -₹10,000.00" in text
    assert "Charged +₹2,000.00" in text
    assert "from Bank ₹5,000.00 in credit" in text
    assert "to Rent ₹5,000.00" in text


def test_card_in_credit_is_never_red(signed_in: Client) -> None:
    card = card_in_credit()

    page = view_page(signed_in, card)
    listed = list_page(signed_in, "liability")

    assert "what you owe ₹5,000.00 in credit" in page_text(page)
    assert "Balance ₹5,000.00 in credit" in page_text(listed)
    for html in (page, listed):
        assert "text-red-600" not in html
        assert "fill-red-300" not in html
    assert "-₹5,000.00" not in page


def test_card_list_row_greens_paying_off_this_month(signed_in: Client) -> None:
    card_in_credit()

    listed = list_page(signed_in, "liability")

    assert '<span class="text-emerald-600">-₹8,000.00</span> this month' in listed


def test_asset_rows_keep_money_in_green_and_out_plain(signed_in: Client) -> None:
    bank = opening("Savings", "asset", "0")
    salary = make_account("Salary", "income")
    rent = make_account("Rent", "expense")
    today = timezone.localdate()
    record(today, salary, bank, "900", "Pay")
    record(today, bank, rent, "300", "Rent")

    page = view_page(signed_in, bank)

    assert '<span class="text-emerald-600">+₹900.00</span>' in page
    assert "<span>-₹300.00</span>" in page


def test_privacy_mode_hides_sign_colour_and_in_credit(
    signed_in: Client, user: User
) -> None:
    card = card_in_credit()
    user.privacy_mode = True
    user.save()

    for html in (view_page(signed_in, card), list_page(signed_in, "liability")):
        assert "in credit" not in html
        assert "+₹" not in html
        assert "-₹" not in html
        assert "text-emerald-600" not in html
        assert 'sr-only">Paid' not in html
        assert 'sr-only">Charged' not in html


def test_forecast_for_a_card_shows_charges_up_and_credit_uncoloured(
    signed_in: Client,
) -> None:
    card = opening("Card", "liability", "-3000")
    make_manual_draft(
        (card, make_account("Dentist", "expense"), "2000"),
        description="Dentist",
        date=timezone.localdate() + timedelta(days=3),
    )

    html = signed_in.get(reverse("forecast") + f"?account={card.pk}").content.decode()

    text = page_text(html)
    assert CHARGED in html
    assert "₹3,000.00 in credit" in text
    assert "₹1,000.00 in credit" in text
    assert "text-red-600" not in html


def test_forecast_for_a_card_greens_a_payment(signed_in: Client) -> None:
    card = opening("Card", "liability", "20000")
    make_manual_draft(
        (opening("Bank", "asset", "0"), card, "10000"),
        description="Pay card",
        date=timezone.localdate() + timedelta(days=3),
    )

    html = signed_in.get(reverse("forecast") + f"?account={card.pk}").content.decode()

    assert PAID in html
