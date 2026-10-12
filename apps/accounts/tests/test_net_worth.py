from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.net_worth import net_worth
from apps.accounts.tests.conftest import (
    account_url,
    edit_account,
    make_account,
    page_text,
)
from apps.accounts.tests.test_balance import opening, record
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def home_page(client: Client, **params: str) -> str:
    return client.get(reverse("index"), params).content.decode()


def home_text(client: Client) -> str:
    return page_text(home_page(client))


def test_no_balance_accounts_shows_zero(signed_in: Client) -> None:
    page = home_text(signed_in)

    assert "Assets ₹0.00" in page
    assert "Liabilities ₹0.00" in page
    assert "Net Worth ₹0.00" in page


def test_net_worth_is_asset_balances(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    opening("Cash", "asset", "50.50")
    salary = make_account("Salary", "income")
    record(signed_in, salary, bank, "200.00")

    page = home_text(signed_in)

    assert "Assets ₹1,250.50" in page
    assert "Net Worth ₹1,250.50" in page


def test_liability_balances_reduce_net_worth(signed_in: Client) -> None:
    opening("Bank", "asset", "3000.00")
    card = opening("Card", "liability", "500.00")
    fuel = make_account("Fuel", "expense")
    record(signed_in, card, fuel, "1200.00")

    page = home_text(signed_in)

    assert "Assets ₹3,000.00" in page
    assert "Liabilities ₹1,700.00" in page
    assert "Net Worth ₹1,300.00" in page


def test_liabilities_above_assets_show_negative_net_worth(signed_in: Client) -> None:
    opening("Bank", "asset", "100.00")
    opening("Loan", "liability", "400.00")

    assert "Net Worth -₹300.00" in home_text(signed_in)


def test_income_and_expense_accounts_never_count(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "100.00")
    salary = make_account("Salary", "income")
    rent = make_account("Rent", "expense")
    record(signed_in, salary, bank, "900.00")
    record(signed_in, bank, rent, "600.00")

    page = home_text(signed_in)

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

    page = home_text(signed_in)

    assert "Assets ₹800.00" in page
    assert "Liabilities ₹300.00" in page
    assert "Net Worth ₹500.00" in page


def test_transactions_after_as_of_date_dont_count(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    salary = make_account("Salary", "income")
    record(signed_in, salary, bank, "200.00")
    response = signed_in.post(
        reverse("transaction_create"),
        form_data(salary, bank, "50.00", date="2026-04-01"),
    )
    assert response.status_code == 302

    assert net_worth(date(2026, 3, 31)).total == Decimal("1200.00")
    assert net_worth(date(2026, 4, 1)).total == Decimal("1250.00")


def test_account_opening_after_as_of_date_counts_as_zero(signed_in: Client) -> None:
    opening("Bank", "asset", "1000.00")
    card = opening("Card", "liability", "300.00")
    edit_account(signed_in, card, opening_balance_date=date(2026, 5, 1))

    before = net_worth(date(2026, 4, 30))
    assert before.liabilities == 0
    assert before.total == Decimal("1000.00")
    assert net_worth(date(2026, 5, 1)).total == Decimal("700.00")


def test_home_page_charts_net_worth_history(signed_in: Client) -> None:
    opening("Bank", "asset", "1000.00")

    page = home_page(signed_in)

    assert "<svg" in page
    assert "Net Worth at each month-end" in page
    assert "31 Jan 2026" in page


def test_no_balance_accounts_shows_no_chart(signed_in: Client) -> None:
    make_account("Salary", "income")

    page = home_page(signed_in)

    assert "<polyline" not in page
    assert "No Net Worth history yet" in page
