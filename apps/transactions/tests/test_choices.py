import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.db.models import ProtectedError
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account
from apps.classification.models import Party
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import form_data, transaction_url

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def select(body: str, name: str) -> str:
    match = re.search(rf'<select name="{name}".*?</select>', body, re.DOTALL)
    assert match
    return match.group()


def test_account_choices_are_grouped_by_kind(signed_in: Client) -> None:
    for name, kind in [
        ("Bank", "asset"),
        ("Card", "liability"),
        ("Groceries", "expense"),
        ("Salary", "income"),
    ]:
        make_account(name, kind)

    body = signed_in.get(reverse("transaction_create")).content.decode()

    choices = select(body, "splits-0-from_account")
    groups = re.findall(
        r'<optgroup label="(\w+)">\s*<option value="\d+">(\w+)', choices
    )
    assert groups == [
        ("Asset", "Bank"),
        ("Liability", "Card"),
        ("Expense", "Groceries"),
        ("Income", "Salary"),
    ]


def test_hidden_accounts_and_parties_are_left_out_of_new_entries(
    signed_in: Client,
) -> None:
    make_account("Old bank", "asset", hidden=True)
    Party.objects.create(name="Closed shop", hidden=True)

    body = signed_in.get(reverse("transaction_create")).content.decode()

    assert "Old bank" not in body
    assert "Closed shop" not in body


def test_hidden_account_cannot_be_posted_on_new_entries(signed_in: Client) -> None:
    old_bank = make_account("Old bank", "asset", hidden=True)
    groceries = make_account("Groceries", "expense")
    shop = Party.objects.create(name="Closed shop", hidden=True)

    response = signed_in.post(
        reverse("transaction_create"), form_data(old_bank, groceries, party=shop.pk)
    )

    assert response.content.decode().count("Select a valid choice.") == 2
    assert not Transaction.objects.exists()


def test_hidden_account_and_party_are_kept_when_editing(signed_in: Client) -> None:
    old_bank = make_account("Old bank", "asset", hidden=True)
    groceries = make_account("Groceries", "expense")
    make_account("Older bank", "asset", hidden=True)
    shop = Party.objects.create(name="Closed shop", hidden=True)
    transaction = Transaction.objects.create(date=date(2026, 3, 1), party=shop)
    split = transaction.splits.create(
        from_account=old_bank, to_account=groceries, amount=Decimal(5)
    )
    url = transaction_url("transaction_edit", transaction)

    body = signed_in.get(url).content.decode()

    assert f'<option value="{old_bank.pk}" selected>Old bank' in body
    assert f'<option value="{shop.pk}" selected>Closed shop' in body
    assert "Older bank" not in body

    response = signed_in.post(
        url, form_data(old_bank, groceries, "6", party=shop.pk, split_id=split.pk)
    )

    assert response["Location"] == reverse("transaction_list")
    assert transaction.splits.get().amount == Decimal(6)


def test_accounts_and_parties_in_use_cannot_be_deleted(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    shop = Party.objects.create(name="Big Bazaar")
    signed_in.post(
        reverse("transaction_create"), form_data(bank, groceries, party=shop.pk)
    )

    for url in [
        account_url("account_delete", bank),
        account_url("account_delete", groceries),
        reverse("party_delete", args=[shop.pk]),
    ]:
        with pytest.raises(ProtectedError):
            signed_in.post(url)
    assert Transaction.objects.get().splits.count() == 1
