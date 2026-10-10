from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin(client: Client, superuser: User) -> Client:
    client.force_login(superuser)
    return client


def admin_rows(
    *rows: tuple[Account, Account], when: str = "2026-03-01"
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "date": when,
        "party": "",
        "description": "",
        "splits-TOTAL_FORMS": str(len(rows)),
        "splits-INITIAL_FORMS": "0",
        "splits-MIN_NUM_FORMS": "0",
        "splits-MAX_NUM_FORMS": "1000",
    }
    for index, (source, destination) in enumerate(rows):
        data |= {
            f"splits-{index}-from_account": source.pk,
            f"splits-{index}-to_account": destination.pk,
            f"splits-{index}-amount": "100",
        }
    return data


def add(client: Client, data: dict[str, Any]) -> str:
    response = client.post(reverse("admin:transactions_transaction_add"), data)
    return response.content.decode()


def test_admin_records_a_valid_transaction(admin: Client) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Groceries", "expense")

    add(admin, admin_rows((bank, food)))

    assert Transaction.objects.get().splits.get().to_account == food


def test_admin_applies_the_direction_rules(admin: Client) -> None:
    bank = make_account("Bank", "asset")
    salary = make_account("Salary", "income")

    body = add(admin, admin_rows((bank, salary)))

    assert "An Income Account can only be a source." in body
    assert not Transaction.objects.exists()


def test_admin_requires_splits_to_share_an_account(admin: Client) -> None:
    bank = make_account("Bank", "asset")
    card = make_account("Card", "liability")
    food = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")

    body = add(admin, admin_rows((bank, food), (card, fuel)))

    assert "Splits must share a From or a To Account." in body
    assert not Transaction.objects.exists()


def test_admin_refuses_a_date_before_an_opening_balance(admin: Client) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Groceries", "expense")

    body = add(admin, admin_rows((bank, food), when="2025-12-31"))

    assert "before the Opening Balance date of Bank" in body
    assert not Transaction.objects.exists()


def test_admin_cannot_change_an_accounts_kind(admin: Client) -> None:
    rent = make_account("Rent", "expense")

    admin.post(
        reverse("admin:accounts_account_change", args=[rent.pk]),
        {"name": "Rent", "kind": "income", "include_in_net_worth": "on"},
    )

    rent.refresh_from_db()
    assert rent.kind == Account.Kind.EXPENSE
