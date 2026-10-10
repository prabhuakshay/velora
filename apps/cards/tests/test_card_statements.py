from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import make_account
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card, record
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def periods() -> list[tuple[date, date, date]]:
    return [
        (statement.period_start, statement.period_end, statement.due_date)
        for statement in Statement.objects.all()
    ]


def test_the_day_after_the_statement_day_creates_a_statement_with_its_estimate(
    card: Account, groceries: Account
) -> None:
    record(card, groceries, "1200", date(2026, 9, 20))
    record(card, groceries, "300", date(2026, 10, 15))

    run_daily_job(date(2026, 10, 16))

    statement = Statement.objects.get()
    assert statement.card == card
    assert periods() == [(date(2026, 9, 16), date(2026, 10, 15), date(2026, 11, 5))]
    assert statement.estimated_amount == Decimal(1500)
    assert statement.amount == Decimal(1500)


def test_a_second_run_on_the_same_day_changes_nothing(
    card: Account, groceries: Account
) -> None:
    record(card, groceries, "1200", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))

    run_daily_job(date(2026, 10, 16))
    run_daily_job(date(2026, 10, 17))

    assert Statement.objects.count() == 1
    assert Draft.objects.count() == 1


def test_the_statement_day_itself_creates_no_statement(card: Account) -> None:
    run_daily_job(date(2026, 9, 16))

    run_daily_job(date(2026, 10, 15))

    assert [period_end for _, period_end, _ in periods()] == [date(2026, 9, 15)]


def test_a_due_day_after_the_statement_day_falls_in_the_same_month() -> None:
    make_card(statement_day=3, due_day=23)

    run_daily_job(date(2026, 10, 4))

    assert periods() == [(date(2026, 9, 4), date(2026, 10, 3), date(2026, 10, 23))]


def test_days_past_a_months_end_fall_on_its_last_day() -> None:
    make_card(statement_day=31, due_day=30)

    run_daily_job(date(2027, 3, 1))

    assert periods() == [(date(2027, 2, 1), date(2027, 2, 28), date(2027, 3, 30))]


def test_a_new_card_starts_with_the_latest_period_still_to_pay() -> None:
    make_card()

    run_daily_job(date(2026, 10, 25))

    assert periods() == [(date(2026, 9, 16), date(2026, 10, 15), date(2026, 11, 5))]


def test_a_new_card_waits_a_day_for_the_period_closing_today() -> None:
    make_card()

    run_daily_job(date(2026, 10, 15))
    assert periods() == []

    run_daily_job(date(2026, 10, 16))
    assert [period_end for _, period_end, _ in periods()] == [date(2026, 10, 15)]


def test_a_new_card_skips_a_period_already_past_its_due_date() -> None:
    make_card()

    run_daily_job(date(2026, 10, 10))

    assert periods() == []


def test_periods_missed_while_the_job_was_down_are_caught_up(card: Account) -> None:
    run_daily_job(date(2026, 8, 16))

    run_daily_job(date(2026, 10, 20))

    assert [period_end for _, period_end, _ in periods()] == [
        date(2026, 8, 15),
        date(2026, 9, 15),
        date(2026, 10, 15),
    ]


def test_cards_without_settings_get_no_statements() -> None:
    make_account("Home loan", "liability")

    run_daily_job(date(2026, 10, 16))

    assert not Statement.objects.exists()


def test_a_statement_proposes_its_payment_as_a_draft_on_the_due_day(
    card: Account, groceries: Account
) -> None:
    record(card, groceries, "1200", date(2026, 9, 20))

    run_daily_job(date(2026, 10, 16))

    draft = Draft.objects.get()
    assert draft.source == Draft.Source.STATEMENT
    assert draft.statement == Statement.objects.get()
    assert draft.date == date(2026, 11, 5)
    assert [
        (split.from_account, split.to_account, split.amount)
        for split in draft.splits.all()
    ] == [(card.pays_from, card, Decimal(1200))]


def test_the_payment_draft_is_never_posted_by_the_job(
    card: Account, groceries: Account
) -> None:
    record(card, groceries, "1200", date(2026, 9, 20))

    run_daily_job(date(2026, 10, 16))
    run_daily_job(date(2026, 11, 10))

    assert Draft.objects.waiting().count() == 1
    assert Transaction.objects.count() == 1


def test_nothing_to_pay_proposes_no_draft(card: Account, groceries: Account) -> None:
    record(groceries, card, "500", date(2026, 9, 20))

    run_daily_job(date(2026, 10, 16))

    assert Statement.objects.get().amount == Decimal(-500)
    assert not Draft.objects.exists()
