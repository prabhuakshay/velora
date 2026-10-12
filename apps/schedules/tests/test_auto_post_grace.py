from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Occurrence
from apps.schedules.occurrences import regenerate
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from apps.schedules.models import Schedule

pytestmark = pytest.mark.django_db


def auto_post_rent(**fields: object) -> Schedule:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    return make_schedule((bank, rent, "25000"), auto_post=True, grace_days=3, **fields)


def assert_drafted_and_waiting(due_date: date) -> None:
    occurrence = Occurrence.objects.get(due_date=due_date)
    assert occurrence.status == Occurrence.Status.DRAFTED
    assert occurrence.draft.status == Draft.Status.WAITING


def test_deleting_an_auto_posted_transaction_leaves_a_waiting_draft() -> None:
    auto_post_rent()
    run_daily_job(date(2026, 10, 5))

    Transaction.objects.get().delete()

    assert_drafted_and_waiting(date(2026, 10, 5))
    run_daily_job(date(2026, 10, 6))
    assert not Transaction.objects.exists()


def test_deleting_a_recorded_covering_transaction_posts_nothing() -> None:
    split = auto_post_rent().splits.get()
    recorded = Transaction.objects.create(date=date(2026, 10, 5))
    recorded.splits.create(
        from_account=split.from_account,
        to_account=split.to_account,
        amount=Decimal(25000),
    )
    run_daily_job(date(2026, 10, 5))
    assert Occurrence.objects.get(due_date=date(2026, 10, 5)).transaction == recorded

    recorded.delete()

    assert_drafted_and_waiting(date(2026, 10, 5))
    run_daily_job(date(2026, 10, 6))
    assert not Transaction.objects.exists()


def test_deleting_a_transaction_from_months_ago_never_posts_again() -> None:
    auto_post_rent(start_date=date(2026, 4, 5))
    run_daily_job(date(2026, 4, 5))

    Transaction.objects.get().delete()
    run_daily_job(date(2026, 10, 12))

    assert not Transaction.objects.exists()
    occurrence = Occurrence.objects.get(due_date=date(2026, 4, 5))
    assert occurrence.status == Occurrence.Status.MISSED
    assert occurrence.draft.status == Draft.Status.WAITING


def test_after_an_outage_only_due_dates_within_grace_are_auto_posted() -> None:
    auto_post_rent(start_date=date(2026, 9, 1), unit="day")
    run_daily_job(date(2026, 9, 1))

    run_daily_job(date(2026, 9, 14))

    due = Occurrence.objects.filter(due_date__lte=date(2026, 9, 14))
    paid = [o.due_date.day for o in due if o.status == Occurrence.Status.PAID]
    missed = [o for o in due if o.status == Occurrence.Status.MISSED]
    assert paid == [1, 11, 12, 13, 14]
    assert [o.due_date.day for o in missed] == list(range(2, 11))
    assert all(o.draft.status == Draft.Status.WAITING for o in missed)


def test_regenerate_auto_posts_due_dates_within_grace() -> None:
    schedule = auto_post_rent(start_date=date(2026, 9, 5), unit="week")

    regenerate(schedule, date(2026, 9, 21))

    assert [t.date for t in Transaction.objects.all()] == [date(2026, 9, 19)]
