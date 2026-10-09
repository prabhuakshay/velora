from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import account_url, edit_account, make_account
from apps.accounts.tests.test_balance import opening, record
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def home_page(client: Client, **params: str) -> str:
    return client.get(reverse("index"), params).content.decode()


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


def test_transactions_after_as_of_date_dont_count(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    salary = make_account("Salary", "income")
    record(signed_in, salary, bank, "200.00")
    response = signed_in.post(
        reverse("transaction_create"),
        form_data(salary, bank, "50.00", date="2026-04-01"),
    )
    assert response.status_code == 302

    assert "Net Worth ₹1200.00" in home_page(signed_in, as_of="2026-03-31")
    assert "Net Worth ₹1250.00" in home_page(signed_in, as_of="2026-04-01")


def test_account_opening_after_as_of_date_counts_as_zero(signed_in: Client) -> None:
    opening("Bank", "asset", "1000.00")
    card = opening("Card", "liability", "300.00")
    edit_account(signed_in, card, opening_balance_date=date(2026, 5, 1))

    before = home_page(signed_in, as_of="2026-04-30")
    assert "Liabilities ₹0.00" in before
    assert "Net Worth ₹1000.00" in before
    assert "Net Worth ₹700.00" in home_page(signed_in, as_of="2026-05-01")


def test_date_input_defaults_to_today(signed_in: Client) -> None:
    today = timezone.localdate().isoformat()

    page = home_page(signed_in)

    assert 'type="date"' in page
    assert f'name="as_of" value="{today}"' in page
    assert f'max="{today}"' in page


@pytest.mark.parametrize("as_of", ["not-a-date", "2026-02-30", "9999-12-31", ""])
def test_invalid_or_future_as_of_date_falls_back_to_today(
    signed_in: Client, as_of: str
) -> None:
    opening("Bank", "asset", "1000.00")

    response = signed_in.get(reverse("index"), {"as_of": as_of})

    assert response.status_code == 200
    page = response.content.decode()
    assert f'value="{timezone.localdate().isoformat()}"' in page
    assert "Net Worth ₹1000.00" in page


def test_home_page_charts_net_worth_history(signed_in: Client) -> None:
    opening("Bank", "asset", "1000.00")

    page = home_page(signed_in)

    assert "<svg" in page
    assert "Net Worth history" in page
    assert "31 Jan 2026" in page


def test_no_balance_accounts_shows_no_chart(signed_in: Client) -> None:
    make_account("Salary", "income")

    page = home_page(signed_in)

    assert "<svg" not in page
    assert "No Net Worth history yet" in page
