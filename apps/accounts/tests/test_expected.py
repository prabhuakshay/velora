from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.expected import expected_spending
from apps.accounts.tests.conftest import make_account
from apps.quick_add.tests.conftest import make_manual_draft
from apps.schedules.occurrences import materialise_occurrences
from apps.schedules.tests.conftest import make_schedule

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 1)
OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))


def test_an_upcoming_occurrence_due_in_the_range_is_expected() -> None:
    rent = make_account("Rent", "expense")
    make_schedule((make_account("Bank", "asset"), rent, "25000"))
    materialise_occurrences(TODAY)

    assert expected_spending(*OCTOBER) == {rent.pk: Decimal(25000)}


def test_occurrences_due_outside_the_range_are_not_expected() -> None:
    rent = make_account("Rent", "expense")
    make_schedule((make_account("Bank", "asset"), rent, "25000"))
    materialise_occurrences(TODAY)

    # Due 5 Oct, still Upcoming, and 5 Nov, beyond the stored Occurrences.
    assert expected_spending(date(2026, 10, 6), date(2026, 11, 4)) == {}
    assert expected_spending(date(2026, 11, 1), date(2026, 11, 30)) == {
        rent.pk: Decimal(25000)
    }


def test_waiting_drafts_dated_in_the_range_are_expected_however_early() -> None:
    bank = make_account("Bank", "asset")
    dentist = make_account("Dentist", "expense")
    make_manual_draft((bank, dentist, "3000"), date=date(2026, 9, 30))
    make_manual_draft((bank, dentist, "2000"), date=date(2026, 10, 2))
    make_manual_draft((bank, dentist, "500"), date=date(2026, 10, 25))
    make_manual_draft((bank, dentist, "900"), date=date(2026, 11, 1))

    assert expected_spending(*OCTOBER) == {dentist.pk: Decimal(2500)}


def test_amountless_occurrences_and_drafts_add_nothing() -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")
    phone = make_account("Phone", "expense")
    make_schedule((bank, power, None))
    make_schedule((bank, phone, "600"), (bank, power, None))
    make_manual_draft((bank, power, None))
    materialise_occurrences(TODAY)

    assert expected_spending(*OCTOBER) == {phone.pk: Decimal(600)}


def test_paused_schedules_are_not_expected() -> None:
    rent = make_account("Rent", "expense")
    make_schedule((make_account("Bank", "asset"), rent, "25000"), active=False)
    materialise_occurrences(TODAY)

    assert expected_spending(*OCTOBER) == {}


def test_transfers_and_income_are_not_expected() -> None:
    bank = make_account("Bank", "asset")
    savings = make_account("Savings", "asset")
    salary = make_account("Salary", "income")
    make_schedule((bank, savings, "10000"), (salary, bank, "90000"))
    make_manual_draft((savings, bank, "5000"))
    materialise_occurrences(TODAY)

    assert expected_spending(*OCTOBER) == {}


def test_a_waiting_refund_takes_away_from_expected() -> None:
    bank = make_account("Bank", "asset")
    shopping = make_account("Shopping", "expense")
    make_manual_draft((bank, shopping, "4000"), date=date(2026, 10, 3))
    make_manual_draft((shopping, bank, "1500"), date=date(2026, 10, 9))

    assert expected_spending(*OCTOBER) == {shopping.pk: Decimal(2500)}
