from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.forecast import forecast
from apps.accounts.tests.conftest import page_text
from apps.cards.models import Statement
from apps.cards.statements import (
    carried_credit,
    enter_actual_amount,
    link_payment,
    unlink_payment,
)
from apps.cards.tests.conftest import record
from apps.cards.tests.test_card_payments import edit_url
from apps.cards.tests.test_statement_part_payments import pay, waiting_amount
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.transactions.models import Transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def october(card: Account, groceries: Account) -> Statement:
    """The card's Statement to 15 Oct 2026, of 10,000 due 5 Nov."""
    record(card, groceries, "10000", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    return Statement.objects.get()


def overpay(statement: Statement, amount: str) -> Transaction:
    payment = pay(statement.card, amount, date(2026, 10, 25))
    link_payment(statement, payment)
    return payment


def next_statement(card: Account, groceries: Account, closing: date) -> Statement:
    """The Statement closing then, with 8,000 spent early in its period."""
    record(card, groceries, "8000", closing.replace(day=1))
    run_daily_job(closing.replace(day=16))
    return Statement.objects.get(period_end=closing)


def test_an_overpayment_lowers_the_next_estimate_and_its_draft(
    signed_in: Client, card: Account, groceries: Account, october: Statement
) -> None:
    overpay(october, "15000")

    november = next_statement(card, groceries, date(2026, 11, 15))

    assert november.estimated_amount == Decimal(3000)
    assert waiting_amount(november) == Decimal(3000)
    text = page_text(signed_in.get(edit_url(november)).content.decode())
    assert f"Credit from {october} -₹5,000.00 Comes to ₹3,000.00" in text
    overpaid = page_text(signed_in.get(edit_url(october)).content.decode())
    assert "₹5,000.00 overpaid carries to the next Statement." in overpaid


def test_credit_carries_until_it_is_used_up(
    signed_in: Client, card: Account, groceries: Account, october: Statement
) -> None:
    overpay(october, "30000")

    november = next_statement(card, groceries, date(2026, 11, 15))
    december = next_statement(card, groceries, date(2026, 12, 15))
    january = next_statement(card, groceries, date(2027, 1, 15))

    assert november.estimated_amount == december.estimated_amount == 0
    assert not Draft.objects.filter(statement__in=[november, december]).exists()
    text = page_text(signed_in.get(edit_url(december)).content.decode())
    assert "Nothing to pay" in text
    assert "₹4,000.00 credit carries to the next Statement." in text
    assert january.estimated_amount == Decimal(4000)


def test_a_refund_beyond_the_spending_carries_to_the_next_statement(
    card: Account, groceries: Account
) -> None:
    record(card, groceries, "8000", date(2026, 9, 20))
    record(groceries, card, "12000", date(2026, 10, 1))
    run_daily_job(date(2026, 10, 16))

    november = next_statement(card, groceries, date(2026, 11, 15))

    assert Statement.objects.get(period_end=date(2026, 10, 15)).amount == 0
    assert november.estimated_amount == Decimal(4000)


def test_an_actual_amount_on_a_paid_statement_changes_the_credit(
    card: Account, groceries: Account, october: Statement
) -> None:
    overpay(october, "15000")
    november = next_statement(card, groceries, date(2026, 11, 15))

    enter_actual_amount(october, Decimal(9000))

    november.refresh_from_db()
    assert november.estimated_amount == Decimal(2000)
    assert waiting_amount(november) == Decimal(2000)


def test_a_paid_statement_passes_on_the_credit_it_now_leaves(
    card: Account, groceries: Account, october: Statement
) -> None:
    overpay(october, "15000")
    november = next_statement(card, groceries, date(2026, 11, 15))
    link_payment(november, pay(card, "3000", date(2026, 11, 20)))
    december = next_statement(card, groceries, date(2026, 12, 15))
    assert december.estimated_amount == Decimal(8000)

    enter_actual_amount(october, Decimal(9000))

    december.refresh_from_db()
    assert december.estimated_amount == Decimal(7000)


def test_an_actual_amount_replaces_the_credit_chain(
    card: Account, october: Statement
) -> None:
    enter_actual_amount(october, Decimal(-11500))

    assert carried_credit(card) == Decimal(11500)


def test_unlinking_the_overpayment_removes_the_credit(
    card: Account, groceries: Account, october: Statement
) -> None:
    payment = overpay(october, "15000")
    november = next_statement(card, groceries, date(2026, 11, 15))

    unlink_payment(october, payment)

    november.refresh_from_db()
    # The payment now counts in November's period, where it is dated.
    assert november.estimated_amount == 0
    october.refresh_from_db()
    assert october.needs_payment


def test_the_forecast_takes_the_carried_credit_off_the_next_card_bill(
    card: Account, groceries: Account, october: Statement
) -> None:
    overpay(october, "15000")
    record(card, groceries, "8000", date(2026, 11, 1))

    result = forecast(date(2026, 11, 2), length=40)

    [bill] = [move for move in result.moves if move.label == f"{card} bill"]
    assert (bill.when, bill.amount) == (date(2026, 12, 5), Decimal(3000))


def test_the_forecast_chains_credit_through_the_bills_it_projects(
    card: Account, groceries: Account, october: Statement
) -> None:
    overpay(october, "30000")
    record(card, groceries, "8000", date(2026, 11, 1))
    record(card, groceries, "8000", date(2026, 12, 1))
    record(card, groceries, "8000", date(2027, 1, 1))

    result = forecast(date(2026, 11, 2), length=100)

    bills = [move for move in result.moves if move.label == f"{card} bill"]
    assert [(bill.when, bill.amount) for bill in bills] == [
        (date(2027, 2, 5), Decimal(4000))
    ]
