from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Account
from apps.accounts.tests.conftest import (
    account_url,
    list_page,
    list_text,
    make_account,
    page_text,
)
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_list_tabs_count_each_kinds_visible_accounts(signed_in: Client) -> None:
    make_account("Bank", "asset")
    make_account("Cash", "asset")
    make_account("Old", "asset", hidden=True)
    make_account("Rent", "expense")

    text = list_text(signed_in, "expense")

    assert "Assets 2 Liabilities 0 Expenses 1 Income 0" in text


def test_list_shows_this_months_spending_and_totals(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "1000")
    rent = make_account("Rent", "expense")
    record(today.replace(day=1), bank, rent, "400", "Rent")
    record(today.replace(day=1) - timedelta(days=1), bank, rent, "350", "Rent")

    expenses = list_text(signed_in, "expense")
    assets = list_text(signed_in, "asset")

    assert "Spent this month ₹400.00" in expenses
    assert "Last month ₹350.00" in expenses
    assert "Total ₹250.00" in assets
    assert "-₹400.00 this month" in assets


def test_list_flags_an_account_past_its_threshold(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "100")
    bank.low_balance_threshold = Decimal(500)
    bank.save()
    card = opening("Card", "liability", "100")
    card.low_balance_threshold = Decimal(50)
    card.save()
    opening("Loan", "liability", "100")

    assert "Below ₹500.00" in list_text(signed_in, "asset")
    liabilities = list_text(signed_in, "liability")
    assert liabilities.count("Owing over") == 1


def test_account_page_shows_running_balances_and_money_in(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "1000")
    salary = make_account("Salary", "income")
    rent = make_account("Rent", "expense")
    record(today, salary, bank, "500", "Pay")
    record(today, bank, rent, "200", "Flat")

    text = page_text(view_page(signed_in, bank))

    assert "Flat -₹200.00 to Rent ₹1,300.00" in text
    assert "Pay +₹500.00 from Salary ₹1,500.00" in text


def test_expense_page_shows_this_month_and_no_balance(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    record(today, bank, rent, "700", "Flat")

    text = page_text(view_page(signed_in, rent))

    assert f"Spent in {today:%B} ₹700.00" in text
    assert "Spent by month" in text
    assert "Next 30 days" not in text


def test_account_page_forecasts_an_asset(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000")

    text = page_text(view_page(signed_in, bank))

    assert "Next 30 days" in text
    assert "Lowest ₹1,000.00" in text


def test_privacy_mode_hides_the_month_chart(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000")
    turn_on(signed_in)

    page = view_page(signed_in, bank)

    assert "Hidden in Privacy Mode" in page
    assert "<line x1=" not in page


def test_unused_account_page_offers_delete_in_place(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")

    page = view_page(signed_in, bank)
    response = signed_in.post(account_url("account_delete", bank))

    assert f'action="{account_url("account_delete", bank)}"' in page
    assert response["Location"] == reverse("account_list", kwargs={"kind": "asset"})
    assert not Account.objects.exists()


def test_used_account_page_explains_why_it_cant_be_deleted(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    record(timezone.localdate(), bank, rent, "10", "Flat")

    page = view_page(signed_in, bank)

    assert "while used by Transactions" in page
    assert f'action="{account_url("account_delete", bank)}"' not in page


@pytest.mark.parametrize(
    ("kind", "side"),
    [("asset", "from"), ("liability", "from"), ("income", "from"), ("expense", "to")],
)
def test_new_transaction_starts_from_the_account(
    signed_in: Client, kind: str, side: str
) -> None:
    account = make_account("Here", kind)

    page = signed_in.get(reverse("transaction_create"), {"account": account.pk})

    body = page.content.decode()
    select = body.split(f'name="splits-0-{side}_account"')[1].split("</select>")[0]
    assert f'value="{account.pk}" selected' in select


def test_new_transaction_ignores_an_unknown_account(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")

    page = signed_in.get(reverse("transaction_create"), {"account": "nope"})

    assert page.status_code == 200
    assert f'value="{bank.pk}" selected' not in page.content.decode()


def test_list_hides_share_bars_in_privacy_mode(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    record(timezone.localdate(), bank, rent, "10", "Flat")
    assert "% of this month" in list_page(signed_in, "expense")

    turn_on(signed_in)

    assert "% of this month" not in list_page(signed_in, "expense")
