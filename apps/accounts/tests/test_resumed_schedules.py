from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.expected import expected_by_account
from apps.accounts.forecast import forecast
from apps.accounts.tests.conftest import make_account
from apps.schedules.models import Occurrence, Schedule
from apps.schedules.occurrences import regenerate
from apps.schedules.tests.conftest import make_schedule

pytestmark = pytest.mark.django_db

PAID = Occurrence.Status.PAID


def resumed(schedule: Schedule, last_paid: date, on: date) -> None:
    schedule.occurrences.create(due_date=last_paid, status=PAID)
    Schedule.objects.filter(pk=schedule.pk).update(resumed_on=on)
    schedule.refresh_from_db()
    regenerate(schedule, on)


def quarterly_rent(opening: str = "50000", threshold: str = "0") -> None:
    bank = make_account("Bank", "asset")
    bank.opening_balance = Decimal(opening)
    bank.low_balance_threshold = Decimal(threshold)
    bank.save()
    schedule = make_schedule(
        (bank, make_account("Rent", "expense"), "5000"),
        start_date=date(2026, 6, 15),
        every=3,
    )
    resumed(schedule, date(2026, 6, 15), date(2026, 10, 12))


@pytest.mark.parametrize("length", [30, 60, 90])
def test_due_dates_while_paused_are_not_forecast(length: int) -> None:
    quarterly_rent()

    moves = forecast(date(2026, 10, 12), length).moves

    assert date(2026, 9, 15) not in [move.when for move in moves]


def test_the_next_due_date_after_resuming_is_still_forecast() -> None:
    quarterly_rent()

    moves = forecast(date(2026, 10, 12), 90).moves

    assert [move.when for move in moves] == [date(2026, 12, 15)]


def test_a_due_date_while_paused_raises_no_breach() -> None:
    quarterly_rent(opening="5500", threshold="1000")

    assert forecast(date(2026, 10, 12), 30).breaches == []


def test_a_due_date_while_paused_is_not_expected() -> None:
    schedule = make_schedule(
        (make_account("Bank", "asset"), make_account("Insurance", "expense"), "9000"),
        start_date=date(2025, 10, 5),
        unit="year",
    )
    resumed(schedule, date(2025, 10, 5), date(2026, 10, 10))

    assert expected_by_account(date(2026, 10, 1), date(2026, 10, 31)) == {}
