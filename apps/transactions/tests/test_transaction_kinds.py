from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import transaction_url

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

INCOME_BADGE = 'text-emerald-700">Income</span>'
TRANSFER_BADGE = 'text-sky-700">Transfer</span>'


def record(*moves: tuple[Account, Account]) -> Transaction:
    transaction = Transaction.objects.create(date=date(2026, 3, 1))
    for source, destination in moves:
        transaction.splits.create(
            from_account=source, to_account=destination, amount=Decimal(100)
        )
    return transaction


def detail(client: Client, transaction: Transaction) -> str:
    return client.get(
        transaction_url("transaction_detail", transaction)
    ).content.decode()


@pytest.fixture
def bank() -> Account:
    return make_account("Bank", "asset")


def test_moving_between_asset_and_liability_is_a_transfer(bank: Account) -> None:
    card = make_account("Card", "liability")

    transaction = record((bank, card))

    assert transaction.is_transfer
    assert not transaction.is_income


def test_spending_is_neither_transfer_nor_income(bank: Account) -> None:
    transaction = record((bank, make_account("Groceries", "expense")))

    assert not transaction.is_transfer
    assert not transaction.is_income


def test_a_split_from_income_makes_it_income(bank: Account) -> None:
    salary = make_account("Salary", "income")
    tax = make_account("Tax", "expense")

    transaction = record((salary, bank), (salary, tax))

    assert transaction.is_income
    assert not transaction.is_transfer


def test_list_marks_income_with_a_plus_and_shows_transfer_badge(
    signed_in: Client, bank: Account
) -> None:
    income = record((make_account("Salary", "income"), bank))
    transfer = record((bank, make_account("Card", "liability")))

    body = signed_in.get(reverse("transaction_list")).content.decode()

    assert "+₹100.00" in body
    assert INCOME_BADGE in detail(signed_in, income)
    assert TRANSFER_BADGE in detail(signed_in, transfer)


def test_privacy_mode_hides_income_and_transfer_hints(
    signed_in: Client, bank: Account
) -> None:
    income = record((make_account("Salary", "income"), bank))
    transfer = record((bank, make_account("Card", "liability")))
    signed_in.post(reverse("privacy_mode_on"))

    body = signed_in.get(reverse("transaction_list")).content.decode()

    assert "+" + "₹" not in body
    assert INCOME_BADGE not in detail(signed_in, income)
    assert TRANSFER_BADGE not in detail(signed_in, transfer)
