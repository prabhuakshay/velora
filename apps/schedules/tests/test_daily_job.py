from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Occurrence
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

pytestmark = pytest.mark.django_db


def test_a_due_schedule_proposes_a_draft() -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    landlord = Party.objects.create(name="Landlord")
    make_schedule((bank, rent, "25000"), party=landlord, description="Flat rent")

    run_daily_job(date(2026, 10, 5))

    draft = Draft.objects.get()
    assert (draft.source, draft.date, draft.party, draft.description) == (
        Draft.Source.SCHEDULE,
        date(2026, 10, 5),
        landlord,
        "Flat rent",
    )
    assert [
        (split.from_account, split.to_account, split.amount)
        for split in draft.splits.all()
    ] == [(bank, rent, Decimal(25000))]


def draft_dates() -> list[date]:
    return [draft.date for draft in Draft.objects.order_by("date")]


def test_the_job_catches_up_every_due_date_it_missed() -> None:
    make_schedule(start_date=date(2026, 7, 5))

    run_daily_job(date(2026, 10, 10))

    assert draft_dates() == [
        date(2026, 7, 5),
        date(2026, 8, 5),
        date(2026, 9, 5),
        date(2026, 10, 5),
    ]


def test_a_second_run_on_the_same_day_proposes_nothing_new() -> None:
    make_schedule(start_date=date(2026, 9, 5))
    run_daily_job(date(2026, 10, 5))

    run_daily_job(date(2026, 10, 5))

    assert draft_dates() == [date(2026, 9, 5), date(2026, 10, 5)]


def test_nothing_is_proposed_before_the_due_date() -> None:
    make_schedule(start_date=date(2026, 10, 5))

    run_daily_job(date(2026, 10, 4))

    assert not Draft.objects.exists()


@pytest.mark.parametrize(
    ("start", "every", "unit", "today", "expected"),
    [
        (
            date(2027, 1, 31),
            1,
            "month",
            date(2027, 4, 30),
            [
                date(2027, 1, 31),
                date(2027, 2, 28),
                date(2027, 3, 31),
                date(2027, 4, 30),
            ],
        ),
        (
            date(2028, 1, 31),
            1,
            "month",
            date(2028, 3, 1),
            [date(2028, 1, 31), date(2028, 2, 29)],
        ),
        (
            date(2026, 11, 30),
            3,
            "month",
            date(2027, 6, 1),
            [date(2026, 11, 30), date(2027, 2, 28), date(2027, 5, 30)],
        ),
        (
            date(2028, 2, 29),
            1,
            "year",
            date(2030, 3, 1),
            [date(2028, 2, 29), date(2029, 2, 28), date(2030, 2, 28)],
        ),
        (
            date(2026, 10, 1),
            2,
            "week",
            date(2026, 10, 29),
            [date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 29)],
        ),
        (
            date(2026, 10, 1),
            10,
            "day",
            date(2026, 10, 25),
            [date(2026, 10, 1), date(2026, 10, 11), date(2026, 10, 21)],
        ),
    ],
)
def test_drafts_fall_on_the_repeat_rules_due_dates(
    start: date, every: int, unit: str, today: date, expected: list[date]
) -> None:
    make_schedule(start_date=start, every=every, unit=unit)

    run_daily_job(today)

    assert draft_dates() == expected


def test_a_schedule_stops_after_its_end_date() -> None:
    make_schedule(start_date=date(2026, 8, 5), ends_on=date(2026, 9, 30))

    run_daily_job(date(2026, 10, 10))

    assert draft_dates() == [date(2026, 8, 5), date(2026, 9, 5)]


def test_a_paused_schedule_proposes_no_drafts() -> None:
    make_schedule(start_date=date(2026, 10, 5), active=False)

    run_daily_job(date(2026, 10, 10))

    assert not Draft.objects.exists()


def test_an_open_amount_schedule_proposes_a_draft_without_an_amount() -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")
    make_schedule((bank, power, None))

    run_daily_job(date(2026, 10, 5))

    assert [split.amount for split in Draft.objects.get().splits.all()] == [None]


def test_a_cron_rule_falls_on_the_nth_weekday() -> None:
    make_schedule(start_date=date(2026, 10, 1), every=None, unit="", cron="0 0 * * 5#2")

    run_daily_job(date(2026, 12, 31))

    assert draft_dates() == [date(2026, 10, 9), date(2026, 11, 13), date(2026, 12, 11)]


def test_a_cron_rule_proposes_once_per_matching_day() -> None:
    make_schedule(start_date=date(2026, 10, 1), every=None, unit="", cron="* * 3 * *")

    run_daily_job(date(2026, 11, 2))

    assert draft_dates() == [date(2026, 10, 3)]


@pytest.mark.parametrize(
    "rule", [{"unit": "month"}, {"every": None, "unit": "", "cron": "0 0 5 * *"}]
)
def test_a_schedule_stops_after_its_number_of_occurrences(
    rule: dict[str, object],
) -> None:
    make_schedule(start_date=date(2026, 7, 5), ends_after=2, **rule)

    run_daily_job(date(2026, 10, 10))

    assert draft_dates() == [date(2026, 7, 5), date(2026, 8, 5)]


def test_an_auto_post_schedule_records_the_transaction_itself() -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    landlord = Party.objects.create(name="Landlord")
    schedule = make_schedule(
        (bank, rent, "25000"),
        party=landlord,
        description="Flat rent",
        start_date=date(2026, 9, 5),
        auto_post=True,
    )

    run_daily_job(date(2026, 10, 5))
    run_daily_job(date(2026, 10, 5))

    transactions = Transaction.objects.order_by("date")
    assert [(t.date, t.party, t.description) for t in transactions] == [
        (date(2026, 9, 5), landlord, "Flat rent"),
        (date(2026, 10, 5), landlord, "Flat rent"),
    ]
    assert [
        (split.from_account, split.to_account, split.amount)
        for split in transactions[0].splits.all()
    ] == [(bank, rent, Decimal(25000))]
    assert not Draft.objects.waiting().exists()
    assert [
        o.status for o in schedule.occurrences.filter(due_date__lte="2026-10-05")
    ] == [
        Occurrence.Status.PAID,
        Occurrence.Status.PAID,
    ]


def test_an_auto_post_that_breaks_the_rules_waits_as_a_draft() -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    make_schedule((bank, rent, "25000"), auto_post=True)
    rent.hidden = True
    rent.save()

    run_daily_job(date(2026, 10, 5))

    assert not Transaction.objects.exists()
    assert Draft.objects.waiting().get().date == date(2026, 10, 5)
