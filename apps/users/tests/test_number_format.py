from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, list_page, make_account
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_net_worth import home_page

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def use_format(user: User, number_format: str) -> None:
    user.number_format = number_format
    user.save()


@pytest.mark.parametrize(
    ("number_format", "amount", "expected"),
    [
        ("indian", "0", "₹0.00"),
        ("indian", "999", "₹999.00"),
        ("indian", "1234.5", "₹1,234.50"),
        ("indian", "1234567.89", "₹12,34,567.89"),
        ("indian", "12345678", "₹1,23,45,678.00"),
        ("international", "0", "₹0.00"),
        ("international", "999", "₹999.00"),
        ("international", "1234567.89", "₹1,234,567.89"),
        ("international", "12345678", "₹12,345,678.00"),
    ],
)
def test_net_worth_follows_number_format(
    signed_in: Client, user: User, number_format: str, amount: str, expected: str
) -> None:
    use_format(user, number_format)
    opening("Bank", "asset", amount)

    assert f"Net Worth {expected}" in home_page(signed_in)


@pytest.mark.parametrize(
    ("number_format", "expected"),
    [("indian", "-₹1,23,456.00"), ("international", "-₹123,456.00")],
)
def test_negative_net_worth_shows_sign_before_rupee_in_red(
    signed_in: Client, user: User, number_format: str, expected: str
) -> None:
    use_format(user, number_format)
    opening("Loan", "liability", "123456")

    page = home_page(signed_in)

    assert f'text-red-600">Net Worth {expected}' in page


def test_default_number_format_is_indian(signed_in: Client) -> None:
    opening("Bank", "asset", "100000")

    page = home_page(signed_in)

    assert "Assets ₹1,00,000.00" in page
    assert "Liabilities ₹0.00" in page
    assert "<td>₹1,00,000.00</td>" in page


def test_international_applies_across_pages(signed_in: Client, user: User) -> None:
    use_format(user, "international")
    bank = opening("Bank", "asset", "1000000")
    rent = make_account("Rent", "expense")
    record(date(2026, 3, 1), bank, rent, "250000", "Rent")

    assert "<td>₹750,000.00</td>" in home_page(signed_in)
    accounts = list_page(signed_in, "asset")
    assert "Balance ₹750,000.00" in accounts
    assert "Opening Balance ₹1,000,000.00" in accounts
    view = view_page(signed_in, bank)
    assert "Balance ₹750,000.00" in view
    assert "Opening Balance ₹1,000,000.00" in view
    assert "₹250,000.00" in view
    assert "₹250,000.00" in signed_in.get(reverse("transaction_list")).content.decode()


def test_amount_inputs_stay_plain(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1234567.89")

    page = signed_in.get(account_url("account_edit", bank)).content.decode()

    assert 'value="1234567.89"' in page
