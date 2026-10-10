from datetime import date

import pytest

from apps.accounts.tests.conftest import make_account
from apps.transactions.split_rules import (
    accounts_error,
    opening_balance_error,
    shared_account_error,
)

pytestmark = pytest.mark.django_db


def test_splits_sharing_a_from_or_a_to_account_pass() -> None:
    assert shared_account_error([(1, 2), (1, 3)]) is None
    assert shared_account_error([(1, 3), (2, 3)]) is None
    assert shared_account_error([]) is None


def test_splits_sharing_no_account_are_refused() -> None:
    assert (
        shared_account_error([(1, 2), (3, 4)])
        == "Splits must share a From or a To Account."
    )


def test_a_split_needs_two_accounts_in_an_allowed_direction() -> None:
    bank = make_account("Bank", "asset")
    salary = make_account("Salary", "income")
    rent = make_account("Rent", "expense")

    assert accounts_error(bank, rent) is None
    assert accounts_error(bank, bank) == "A Split cannot go from an Account to itself."
    assert accounts_error(bank, salary) == "An Income Account can only be a source."


def test_a_date_before_an_accounts_opening_balance_is_refused() -> None:
    bank = make_account("Bank", "asset")

    assert opening_balance_error(bank, date(2026, 1, 1)) is None
    assert opening_balance_error(bank, date(2025, 12, 31)) == (
        "The date cannot be before the Opening Balance date of Bank (1 Jan 2026)."
    )
