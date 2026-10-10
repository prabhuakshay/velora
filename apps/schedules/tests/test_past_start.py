from datetime import date

import pytest

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence
from apps.schedules.occurrences import materialise, propose_due_drafts, regenerate
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 10)
TWO_YEARS_AGO = date(2024, 10, 7)


def occurrence_dates() -> list[date]:
    return [
        occurrence.due_date for occurrence in Occurrence.objects.order_by("due_date")
    ]


def test_materialise_creates_no_occurrence_older_than_the_grace_period() -> None:
    schedule = make_schedule(start_date=TWO_YEARS_AGO, grace_days=3)

    materialise(schedule, TODAY)

    assert occurrence_dates() == [date(2026, 10, 7), date(2026, 11, 7)]


def test_materialise_skips_a_due_date_just_outside_the_grace_period() -> None:
    schedule = make_schedule(start_date=TWO_YEARS_AGO, grace_days=2)

    materialise(schedule, TODAY)

    assert occurrence_dates() == [date(2026, 11, 7)]


def test_regenerate_drafts_only_the_occurrences_inside_the_grace_period() -> None:
    schedule = make_schedule(start_date=TWO_YEARS_AGO, unit="week", grace_days=12)

    regenerate(schedule, TODAY)

    assert [draft.date for draft in Draft.objects.order_by("date")] == [
        date(2026, 9, 28),
        date(2026, 10, 5),
    ]


def test_propose_due_drafts_auto_posts_nothing_before_the_grace_period() -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    schedule = make_schedule(
        (bank, rent, "25000"), start_date=TWO_YEARS_AGO, auto_post=True, grace_days=3
    )
    materialise(schedule, TODAY)

    propose_due_drafts(TODAY)

    assert [transaction.date for transaction in Transaction.objects.all()] == [
        date(2026, 10, 7)
    ]
