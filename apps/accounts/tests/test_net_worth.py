from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account
from apps.accounts.tests.test_balance import opening, record

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def home_page(client: Client) -> str:
    return client.get(reverse("index")).content.decode()


def test_no_balance_accounts_shows_zero(signed_in: Client) -> None:
    page = home_page(signed_in)

    assert "Assets ₹0.00" in page
    assert "Liabilities ₹0.00" in page
    assert "Net Worth ₹0.00" in page


def test_net_worth_is_asset_balances(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    opening("Cash", "asset", "50.50")
    salary = make_account("Salary", "income")
    record(signed_in, salary, bank, "200.00")

    page = home_page(signed_in)

    assert "Assets ₹1250.50" in page
    assert "Net Worth ₹1250.50" in page


def test_liability_balances_reduce_net_worth(signed_in: Client) -> None:
    opening("Bank", "asset", "3000.00")
    card = opening("Card", "liability", "500.00")
    fuel = make_account("Fuel", "expense")
    record(signed_in, card, fuel, "1200.00")

    page = home_page(signed_in)

    assert "Assets ₹3000.00" in page
    assert "Liabilities ₹1700.00" in page
    assert "Net Worth ₹1300.00" in page


def test_liabilities_above_assets_show_negative_net_worth(signed_in: Client) -> None:
    opening("Bank", "asset", "100.00")
    opening("Loan", "liability", "400.00")

    assert "Net Worth ₹-300.00" in home_page(signed_in)


def test_income_and_expense_accounts_never_count(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "100.00")
    salary = make_account("Salary", "income")
    rent = make_account("Rent", "expense")
    record(signed_in, salary, bank, "900.00")
    record(signed_in, bank, rent, "600.00")

    page = home_page(signed_in)

    assert "Assets ₹400.00" in page
    assert "Liabilities ₹0.00" in page
    assert "Net Worth ₹400.00" in page


def test_hidden_accounts_still_count(signed_in: Client) -> None:
    for account in (
        opening("Old Bank", "asset", "800.00"),
        opening("Old Card", "liability", "300.00"),
    ):
        response = signed_in.post(account_url("account_hide", account))
        assert response.status_code == 302

    page = home_page(signed_in)

    assert "Assets ₹800.00" in page
    assert "Liabilities ₹300.00" in page
    assert "Net Worth ₹500.00" in page
