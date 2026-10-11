from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.cards.models import CardEMI
from apps.cards.tests.conftest import make_card_emi, record
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def card_page(client: Client, card: Account) -> str:
    return client.get(account_url("account_transactions", card)).content.decode()


def test_a_card_purchase_offers_to_become_a_card_emi(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    purchase = record(card, groceries, "60000", date(2026, 8, 20))

    assert reverse("card_emi_create", args=[purchase.pk]) in card_page(signed_in, card)


def test_a_purchase_becomes_a_card_emi(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    purchase = record(card, groceries, "60000", date(2026, 8, 20))
    interest = make_account("Bank charges", "expense")
    url = reverse("card_emi_create", args=[purchase.pk])

    form = signed_in.get(url).content.decode()
    response = signed_in.post(
        url,
        {
            "principal": "60000",
            "months": "6",
            "annual_rate": "0",
            "processing_fee": "0",
            "first_statement": "2026-09-15",
            "interest_account": interest.pk,
        },
    )

    assert 'value="60000.00"' in form
    assert "15 Oct 2026" in form
    emi = CardEMI.objects.get()
    assert response["Location"] == reverse("card_emi_detail", args=[emi.pk])
    assert (emi.card, emi.purchase, emi.principal, emi.annual_rate) == (
        card,
        purchase,
        Decimal(60000),
        Decimal(0),
    )


def test_a_purchase_off_a_card_cannot_become_a_card_emi(
    signed_in: Client, groceries: Account
) -> None:
    bank = make_account("Bank", "asset")
    purchase = record(bank, groceries, "500", date(2026, 8, 20))

    response = signed_in.get(reverse("card_emi_create", args=[purchase.pk]))

    assert response.status_code == 404


def test_the_card_shows_each_card_emis_progress(
    signed_in: Client, card: Account
) -> None:
    make_card_emi(card, bought_on=date(2020, 1, 1), first_statement=date(2020, 1, 15))
    make_card_emi(
        card,
        months=6,
        bought_on=date(2099, 1, 1),
        first_statement=date(2099, 1, 15),
    )

    page = card_page(signed_in, card)

    assert "12 paid · 0 left · ends Dec 2020" in page
    assert "0 paid · 6 left · ends Jun 2099" in page


def test_foreclosing_bills_the_rest_at_once(signed_in: Client, card: Account) -> None:
    emi = make_card_emi(
        card, bought_on=date(2099, 1, 1), first_statement=date(2099, 1, 15)
    )

    response = signed_in.post(
        reverse("card_emi_foreclose", args=[emi.pk]),
        {"foreclosed_on": "2099-03-01", "foreclosure_fee": "1000"},
    )

    assert response["Location"] == reverse("card_emi_detail", args=[emi.pk])
    emi.refresh_from_db()
    assert (emi.foreclosed_on, emi.foreclosure_fee) == (date(2099, 3, 1), Decimal(1000))
    assert "0 paid · 2 left · ends Mar 2099" in card_page(signed_in, card)


def test_the_form_previews_each_installment_as_the_terms_change(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    purchase = record(card, groceries, "1200", date(2026, 8, 20))

    page = signed_in.get(
        reverse("card_emi_create", args=[purchase.pk]),
        {
            "principal": "1200",
            "months": "12",
            "annual_rate": "0",
            "processing_fee": "",
            "first_statement": "2026-09-15",
        },
    )

    text = page_text(page.content.decode())
    assert "Each month ₹100.00" in text
    assert "12 months · ends Aug 2027" in text
    assert "15 Sep 2026 ₹100.00 principal ₹100.00" in text
    assert not CardEMI.objects.exists()


def test_the_form_waits_for_every_term_before_previewing(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    purchase = record(card, groceries, "1200", date(2026, 8, 20))

    url = reverse("card_emi_create", args=[purchase.pk])

    for terms in ({}, {"principal": "1200", "months": "12"}):
        page = signed_in.get(url, terms).content.decode()
        assert "Enter the months and interest rate" in page


def test_the_card_emi_page_shows_whats_billed_and_whats_next(
    signed_in: Client, card: Account
) -> None:
    emi = make_card_emi(
        card,
        principal="600",
        months=6,
        annual_rate="0",
        bought_on=date(2099, 1, 1),
        first_statement=date(2099, 1, 15),
    )

    page = signed_in.get(reverse("card_emi_detail", args=[emi.pk])).content.decode()

    text = page_text(page)
    assert "₹100.00 a month" in text
    assert "0 of 6 billed · ends Jun 2099" in text
    assert "Next ₹100.00 with the Statement to 15 Jan 2099" in text
    assert reverse("card_emi_foreclose", args=[emi.pk]) in page
    assert reverse("card_emi_detail", args=[emi.pk]) in card_page(signed_in, card)


def test_the_card_emi_page_masks_amounts_in_privacy_mode(
    signed_in: Client, card: Account
) -> None:
    emi = make_card_emi(card, principal="600", months=6, annual_rate="0")
    turn_on(signed_in)

    page = signed_in.get(reverse("card_emi_detail", args=[emi.pk])).content.decode()

    assert "₹100.00" not in page
    assert reverse("card_emi_foreclose", args=[emi.pk]) not in page


@pytest.mark.parametrize(
    ("on", "error"),
    [
        ("2026-08-01", "before the purchase"),
        ("2027-09-01", "nothing is left to foreclose"),
    ],
)
def test_a_foreclosure_must_fall_while_installments_are_left(
    signed_in: Client, card: Account, on: str, error: str
) -> None:
    emi = make_card_emi(card)

    response = signed_in.post(
        reverse("card_emi_foreclose", args=[emi.pk]),
        {"foreclosed_on": on, "foreclosure_fee": "0"},
    )

    assert error in response.content.decode()
    emi.refresh_from_db()
    assert emi.foreclosed_on is None


def test_the_foreclose_form_previews_what_it_saves(
    signed_in: Client, card: Account
) -> None:
    emi = make_card_emi(
        card, bought_on=date(2099, 1, 1), first_statement=date(2099, 1, 15)
    )

    page = signed_in.get(
        reverse("card_emi_foreclose", args=[emi.pk]),
        {"foreclosed_on": "2099-03-01", "foreclosure_fee": "1000"},
    )

    text = page_text(page.content.decode())
    assert "Billed with the Statement to 15 Mar 2099" in text
    assert "Net saving" in text
    emi.refresh_from_db()
    assert emi.foreclosed_on is None
