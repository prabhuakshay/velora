from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from apps.accounts.tests.conftest import account_url, make_account
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card, make_card_emi

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def card_data(card: Account, **settings: Any) -> dict[str, Any]:
    return {
        "name": card.name,
        "opening_balance": "0",
        "opening_balance_date": "2026-01-01",
        "include_in_net_worth": "on",
        "statement_day": "",
        "due_day": "",
        "pays_from": "",
        **settings,
    }


def test_a_liability_account_saves_its_card_settings(signed_in: Client) -> None:
    card = make_account("HDFC card", "liability")
    bank = make_account("Bank", "asset")

    response = signed_in.post(
        account_url("account_edit", card),
        card_data(card, statement_day="15", due_day="5", pays_from=bank.pk),
    )

    assert response.status_code == 302
    card.refresh_from_db()
    assert (card.statement_day, card.due_day, card.pays_from) == (15, 5, bank)


@pytest.mark.parametrize(
    "partial",
    [
        {"statement_day": "15"},
        {"due_day": "5"},
        {"statement_day": "15", "due_day": "5"},
    ],
)
def test_partial_card_settings_are_refused(
    signed_in: Client, partial: dict[str, str]
) -> None:
    card = make_account("HDFC card", "liability")

    response = signed_in.post(
        account_url("account_edit", card), card_data(card, **partial)
    )

    assert response.status_code == 200
    assert "Set the Statement Day, Due Day and" in response.content.decode()
    card.refresh_from_db()
    assert card.statement_day is None


def test_a_card_pays_only_from_an_asset_account(signed_in: Client) -> None:
    card = make_account("HDFC card", "liability")
    other_card = make_account("ICICI card", "liability")

    response = signed_in.post(
        account_url("account_edit", card),
        card_data(card, statement_day="15", due_day="5", pays_from=other_card.pk),
    )

    assert response.status_code == 200
    card.refresh_from_db()
    assert card.pays_from is None


def test_a_day_past_31_is_refused(signed_in: Client) -> None:
    card = make_account("HDFC card", "liability")
    bank = make_account("Bank", "asset")

    response = signed_in.post(
        account_url("account_edit", card),
        card_data(card, statement_day="32", due_day="5", pays_from=bank.pk),
    )

    assert response.status_code == 200


def test_only_liability_accounts_get_card_settings(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    card = make_account("HDFC card", "liability")

    assert (
        "Statement Day"
        not in signed_in.get(account_url("account_edit", bank)).content.decode()
    )
    assert (
        "Statement Day"
        in signed_in.get(account_url("account_edit", card)).content.decode()
    )


def test_card_settings_with_statements_cant_be_cleared(signed_in: Client) -> None:
    card = make_card()
    Statement.objects.create(
        card=card,
        period_start=date(2026, 8, 16),
        period_end=date(2026, 9, 15),
        due_date=date(2026, 10, 5),
        estimated_amount=Decimal(0),
    )

    response = signed_in.post(account_url("account_edit", card), card_data(card))

    assert response.status_code == 200
    assert "so its card settings can" in response.content.decode()
    card.refresh_from_db()
    assert card.is_card


def test_card_settings_with_card_emis_cant_be_cleared(signed_in: Client) -> None:
    card = make_card()
    make_card_emi(card)

    response = signed_in.post(account_url("account_edit", card), card_data(card))

    assert response.status_code == 200
    card.refresh_from_db()
    assert card.is_card


def test_unused_card_settings_can_be_cleared(signed_in: Client) -> None:
    card = make_card()

    response = signed_in.post(account_url("account_edit", card), card_data(card))

    assert response.status_code == 302
    card.refresh_from_db()
    assert not card.is_card
