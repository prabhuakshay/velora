from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.forecast import forecast
from apps.accounts.tests.conftest import make_account
from apps.cards.statements import create_statements
from apps.cards.tests.conftest import make_card, record
from apps.classification.models import Party
from apps.quick_add.tests.conftest import make_manual_draft
from apps.schedules.occurrences import materialise_occurrences, propose_due_drafts
from apps.schedules.tests.conftest import make_schedule, paid

if TYPE_CHECKING:
    from apps.accounts.forecast import Forecast
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 1)


def bank(opening: str = "50000") -> Account:
    account = make_account("Bank", "asset")
    account.opening_balance = Decimal(opening)
    account.save()
    return account


def balance_on(result: Forecast, account: Account, on: date) -> Decimal:
    [row] = [row for row in result.accounts if row.account == account]
    return dict(zip(result.days, row.balances, strict=True))[on]


def test_an_upcoming_occurrence_moves_the_balance_on_its_due_date() -> None:
    savings = bank()
    make_schedule((savings, make_account("Rent", "expense"), "25000"))
    materialise_occurrences(TODAY)

    result = forecast(TODAY)

    assert len(result.days) == 30
    assert result.days[0] == TODAY
    assert balance_on(result, savings, date(2026, 10, 4)) == Decimal(50000)
    assert balance_on(result, savings, date(2026, 10, 5)) == Decimal(25000)
    assert balance_on(result, savings, date(2026, 10, 30)) == Decimal(25000)


def test_a_waiting_draft_moves_the_balance_on_its_date() -> None:
    savings = bank()
    make_manual_draft((savings, make_account("Dentist", "expense"), "3000"))

    result = forecast(TODAY)

    assert balance_on(result, savings, date(2026, 10, 7)) == Decimal(50000)
    assert balance_on(result, savings, date(2026, 10, 8)) == Decimal(47000)


def test_a_draft_dated_before_the_start_lands_on_the_first_day() -> None:
    savings = bank()
    make_manual_draft((savings, make_account("Dentist", "expense"), "3000"))

    result = forecast(date(2026, 10, 10))

    assert balance_on(result, savings, date(2026, 10, 10)) == Decimal(47000)


def test_an_amountless_draft_is_listed_but_left_out_of_totals() -> None:
    savings = bank()
    draft = make_manual_draft(
        (savings, make_account("Dentist", "expense"), None), description="Dentist"
    )

    result = forecast(TODAY)

    assert balance_on(result, savings, date(2026, 10, 30)) == Decimal(50000)
    [item] = result.amountless
    assert (item.when, item.label) == (draft.date, "Dentist")


def test_an_occurrence_with_a_waiting_draft_counts_once() -> None:
    savings = bank()
    make_schedule((savings, make_account("Rent", "expense"), "25000"))
    materialise_occurrences(date(2026, 10, 5))
    propose_due_drafts(date(2026, 10, 5))

    result = forecast(TODAY)

    assert balance_on(result, savings, date(2026, 10, 30)) == Decimal(25000)


def test_an_open_amount_occurrence_uses_the_last_paid_amount() -> None:
    savings = bank()
    power = make_account("Electricity", "expense")
    board = Party.objects.create(name="BESCOM")
    paid(
        (savings, power), board, ("1800", date(2026, 9, 5)), ("2100", date(2026, 9, 28))
    )
    make_schedule((savings, power, None), party=board)
    materialise_occurrences(TODAY)

    result = forecast(TODAY)

    assert balance_on(result, savings, date(2026, 10, 5)) == Decimal(
        50000 - 3900 - 2100
    )
    assert result.amountless == []


def test_an_open_amount_occurrence_never_paid_is_listed_as_amountless() -> None:
    savings = bank()
    make_schedule(
        (savings, make_account("Electricity", "expense"), None),
        description="Electricity bill",
    )
    materialise_occurrences(TODAY)

    result = forecast(TODAY)

    assert balance_on(result, savings, date(2026, 10, 30)) == Decimal(50000)
    [item] = result.amountless
    assert (item.when, item.label) == (date(2026, 10, 5), "Electricity bill")


def test_a_card_pays_its_coming_statement_on_its_due_day() -> None:
    savings = bank()
    card = make_card(pays_from=savings)
    record(card, make_account("Groceries", "expense"), "12000", date(2026, 10, 3))

    result = forecast(date(2026, 10, 10))

    assert balance_on(result, card, date(2026, 11, 4)) == Decimal(12000)
    assert balance_on(result, card, date(2026, 11, 5)) == Decimal(0)
    assert balance_on(result, savings, date(2026, 11, 5)) == Decimal(38000)


def test_a_statement_with_a_payment_draft_is_paid_once() -> None:
    savings = bank()
    card = make_card(pays_from=savings)
    record(card, make_account("Groceries", "expense"), "12000", date(2026, 10, 3))
    create_statements(date(2026, 10, 16))

    result = forecast(date(2026, 10, 16))

    assert balance_on(result, savings, date(2026, 11, 14)) == Decimal(38000)


def test_a_breach_names_the_account_and_first_day_under_its_threshold() -> None:
    savings = bank()
    savings.low_balance_threshold = Decimal(30000)
    savings.save()
    rent = make_account("Rent", "expense")
    make_schedule((savings, rent, "15000"), start_date=date(2026, 10, 5))
    make_schedule((savings, rent, "10000"), start_date=date(2026, 10, 20))
    materialise_occurrences(TODAY)

    result = forecast(TODAY)

    [breach] = result.breaches
    assert (breach.account, breach.on, breach.balance) == (
        savings,
        date(2026, 10, 20),
        Decimal(25000),
    )


def test_the_threshold_defaults_to_zero() -> None:
    savings = bank("1000")
    make_account("Card", "liability")
    make_manual_draft((savings, make_account("Dentist", "expense"), "1000"))
    make_manual_draft(
        (savings, make_account("Gym", "expense"), "1"), date=date(2026, 10, 9)
    )

    result = forecast(TODAY)

    [breach] = result.breaches
    assert (breach.account, breach.on) == (savings, date(2026, 10, 9))
