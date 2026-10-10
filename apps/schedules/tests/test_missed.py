from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Occurrence
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.schedules.models import Schedule

pytestmark = pytest.mark.django_db


def rent_schedule(**fields: object) -> Schedule:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    return make_schedule((bank, rent, "25000"), **fields)


def first_status() -> str:
    return Occurrence.objects.all()[0].status


def test_an_uncovered_occurrence_is_missed_after_the_grace_period() -> None:
    rent_schedule()

    run_daily_job(date(2026, 10, 9))

    assert first_status() == Occurrence.Status.MISSED


def test_an_occurrence_is_not_missed_on_the_last_day_of_its_grace_period() -> None:
    rent_schedule()

    run_daily_job(date(2026, 10, 8))

    assert first_status() == Occurrence.Status.DRAFTED


def test_each_schedule_sets_its_own_grace_period() -> None:
    rent_schedule(grace_days=10)

    run_daily_job(date(2026, 10, 15))
    assert first_status() == Occurrence.Status.DRAFTED

    run_daily_job(date(2026, 10, 16))
    assert first_status() == Occurrence.Status.MISSED


def test_a_skipped_occurrence_is_never_missed(signed_in: Client) -> None:
    rent_schedule()
    run_daily_job(date(2026, 10, 5))
    signed_in.post(reverse("draft_reject", args=[Draft.objects.get().pk]))

    run_daily_job(date(2026, 10, 20))

    assert first_status() == Occurrence.Status.SKIPPED


def test_missing_salary_is_missed() -> None:
    employer = make_account("Salary", "income")
    bank = make_account("Bank", "asset")
    make_schedule((employer, bank, "90000"), start_date=date(2026, 10, 1))

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.MISSED


def test_running_twice_on_the_same_day_keeps_the_occurrence_missed() -> None:
    rent_schedule()
    run_daily_job(date(2026, 10, 9))

    run_daily_job(date(2026, 10, 9))

    assert first_status() == Occurrence.Status.MISSED
    assert Draft.objects.count() == 1


def test_a_missed_occurrence_is_paid_once_a_late_transaction_covers_it() -> None:
    schedule = rent_schedule()
    run_daily_job(date(2026, 10, 9))
    split = schedule.splits.get()
    Transaction.objects.create(date=date(2026, 10, 9)).splits.create(
        from_account=split.from_account,
        to_account=split.to_account,
        amount=Decimal(25000),
    )

    run_daily_job(date(2026, 10, 9))

    assert first_status() == Occurrence.Status.PAID
    assert not Draft.objects.exists()


def test_missed_occurrences_show_in_the_schedules_history(signed_in: Client) -> None:
    schedule = rent_schedule()
    run_daily_job(date(2026, 10, 9))

    response = signed_in.get(reverse("schedule_detail", args=[schedule.pk]))

    assert "5 Oct 2026 · Missed" in response.content.decode()
