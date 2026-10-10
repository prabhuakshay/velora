from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account
from apps.cards.models import CardEMI
from apps.cards.tests.conftest import make_card_emi, record

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
    assert response["Location"] == account_url("account_transactions", card)
    emi = CardEMI.objects.get()
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

    assert response["Location"] == account_url("account_transactions", card)
    emi.refresh_from_db()
    assert (emi.foreclosed_on, emi.foreclosure_fee) == (date(2099, 3, 1), Decimal(1000))
    assert "0 paid · 2 left · ends Mar 2099" in card_page(signed_in, card)
