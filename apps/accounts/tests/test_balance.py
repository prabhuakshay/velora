from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import list_page, make_account
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def opening(name: str, kind: str, amount: str) -> Account:
    account = make_account(name, kind)
    account.opening_balance = Decimal(amount)
    account.save()
    return account


def record(client: Client, source: Account, destination: Account, amount: str) -> None:
    response = client.post(
        reverse("transaction_create"), form_data(source, destination, amount)
    )
    assert response.status_code == 302


def test_transfer_moves_balance_between_assets(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    cash = opening("Cash", "asset", "50.00")

    record(signed_in, bank, cash, "200.00")

    page = list_page(signed_in, "asset")
    assert "Balance ₹800.00" in page
    assert "Balance ₹250.00" in page


def test_spending_lowers_asset_balance(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    groceries = make_account("Groceries", "expense")

    record(signed_in, bank, groceries, "300.25")

    assert "Balance ₹699.75" in list_page(signed_in, "asset")


def test_salary_raises_asset_balance(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    salary = make_account("Salary", "income")

    record(signed_in, salary, bank, "5000.00")

    assert "Balance ₹6000.00" in list_page(signed_in, "asset")


def test_refund_raises_asset_balance(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    clothes = make_account("Clothes", "expense")
    record(signed_in, bank, clothes, "400.00")

    record(signed_in, clothes, bank, "150.00")

    assert "Balance ₹750.00" in list_page(signed_in, "asset")


def test_overspending_shows_negative_asset_balance(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "100.00")
    rent = make_account("Rent", "expense")

    record(signed_in, bank, rent, "250.00")

    assert "Balance ₹-150.00" in list_page(signed_in, "asset")


def test_card_spending_raises_what_is_owed(signed_in: Client) -> None:
    card = opening("Card", "liability", "500.00")
    fuel = make_account("Fuel", "expense")

    record(signed_in, card, fuel, "1200.00")

    assert "Balance ₹1700.00" in list_page(signed_in, "liability")


def test_card_payment_lowers_what_is_owed_and_the_asset(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "3000.00")
    card = opening("Card", "liability", "2000.00")

    record(signed_in, bank, card, "1500.00")

    assert "Balance ₹500.00" in list_page(signed_in, "liability")
    assert "Balance ₹1500.00" in list_page(signed_in, "asset")


def test_account_without_splits_shows_opening_balance(signed_in: Client) -> None:
    opening("Card", "liability", "75.50")

    assert "Balance ₹75.50" in list_page(signed_in, "liability")
