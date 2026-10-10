from datetime import date
from typing import TYPE_CHECKING

import pytest

from apps.accounts.models import Account
from apps.accounts.tests.conftest import account_url, make_account
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card, record
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def merge(client: Client, source: Account, target: Account) -> str:
    response = client.post(
        account_url("account_merge", source), {"target": target.pk}, follow=True
    )
    return response.content.decode()


def test_merging_a_pays_from_account_repoints_the_card(signed_in: Client) -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    card = make_card(pays_from=old_bank)

    merge(signed_in, old_bank, bank)

    card.refresh_from_db()
    assert card.pays_from == bank


def test_merging_a_card_moves_its_settings_and_statements(signed_in: Client) -> None:
    old_card = make_card("Old card", statement_day=20, due_day=10)
    card = make_account("Card", "liability")
    record(old_card, make_account("Groceries", "expense"), "900", date(2026, 10, 1))
    run_daily_job(date(2026, 10, 20))

    merge(signed_in, old_card, card)

    card.refresh_from_db()
    assert (card.statement_day, card.due_day, card.pays_from) == (
        20,
        10,
        old_card.pays_from,
    )
    assert Statement.objects.get().card == card
    assert Draft.objects.get().splits.get().to_account == card


def test_merging_into_a_card_keeps_the_targets_settings(signed_in: Client) -> None:
    old_card = make_account("Old card", "liability")
    card = make_card("Card")

    merge(signed_in, old_card, card)

    card.refresh_from_db()
    assert card.statement_day == 15


def test_merging_one_card_into_another_is_refused(signed_in: Client) -> None:
    old_card = make_card("Old card")
    card = make_card("Card")

    body = merge(signed_in, old_card, card)

    assert "both credit cards" in body
    assert Account.objects.filter(pk=old_card.pk).exists()


def test_deleting_a_pays_from_account_sends_the_user_to_merge(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    make_card(pays_from=bank)

    response = signed_in.post(account_url("account_delete", bank))

    assert response["Location"] == account_url("account_merge", bank)
    assert Account.objects.filter(pk=bank.pk).exists()
