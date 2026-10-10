from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.matching import MATCH_WINDOW, match_transactions
from apps.schedules.models import Occurrence
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


@pytest.fixture
def bank() -> Account:
    return make_account("Bank", "asset")


@pytest.fixture
def rent() -> Account:
    return make_account("Rent", "expense")


def record(
    source: Account,
    destination: Account,
    amount: str,
    on: date,
    party: Party | None = None,
) -> None:
    Transaction.objects.create(date=on, party=party).splits.create(
        from_account=source, to_account=destination, amount=Decimal(amount)
    )


def first_status() -> str:
    return Occurrence.objects.all()[0].status


def test_a_recorded_transaction_marks_a_drafted_occurrence_paid(
    bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "25000"))
    run_daily_job(date(2026, 10, 5))

    record(bank, rent, "25000", date(2026, 10, 6))
    run_daily_job(date(2026, 10, 6))

    assert first_status() == Occurrence.Status.PAID
    assert not Draft.objects.exists()


def test_a_transaction_recorded_before_the_due_date_means_no_draft_is_proposed(
    bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "25000"))
    record(bank, rent, "25000", date(2026, 10, 2))

    run_daily_job(date(2026, 10, 2))
    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.PAID
    assert not Draft.objects.exists()


@pytest.mark.parametrize(
    ("amount", "on"),
    [
        ("22500", date(2026, 10, 5)),
        ("27500", date(2026, 10, 5)),
        ("25000", date(2026, 9, 30)),
        ("25000", date(2026, 10, 10)),
    ],
)
def test_a_transaction_at_the_edge_of_the_tolerances_matches(
    bank: Account, rent: Account, amount: str, on: date
) -> None:
    make_schedule((bank, rent, "25000"))
    record(bank, rent, amount, on)

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.PAID


@pytest.mark.parametrize(
    ("amount", "on"),
    [
        ("22499.99", date(2026, 10, 5)),
        ("27500.01", date(2026, 10, 5)),
        ("25000", date(2026, 9, 29)),
        ("25000", date(2026, 10, 11)),
    ],
)
def test_a_transaction_outside_the_tolerances_does_not_match(
    bank: Account, rent: Account, amount: str, on: date
) -> None:
    make_schedule((bank, rent, "25000"))
    record(bank, rent, amount, on)

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.DRAFTED
    assert Draft.objects.count() == 1


def test_a_transaction_between_other_accounts_does_not_match(
    bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "25000"))
    record(make_account("Cash", "asset"), rent, "25000", date(2026, 10, 5))

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.DRAFTED


def test_any_amount_matches_an_open_amount_schedule(bank: Account) -> None:
    power = make_account("Electricity", "expense")
    make_schedule((bank, power, None))
    record(bank, power, "3127.40", date(2026, 10, 7))

    run_daily_job(date(2026, 10, 7))

    assert first_status() == Occurrence.Status.PAID
    assert not Draft.objects.exists()


def statuses() -> list[str]:
    return [occurrence.status for occurrence in Occurrence.objects.all()]


def test_a_transaction_covers_only_one_occurrence(bank: Account, rent: Account) -> None:
    make_schedule((bank, rent, "25000"))
    make_schedule((bank, rent, "25000"))
    record(bank, rent, "25000", date(2026, 10, 5))

    run_daily_job(date(2026, 10, 5))

    due = Occurrence.objects.filter(due_date=date(2026, 10, 5))
    assert sorted(occurrence.status for occurrence in due) == [
        Occurrence.Status.DRAFTED,
        Occurrence.Status.PAID,
    ]


def test_a_posted_schedule_draft_does_not_cover_the_next_occurrence(
    signed_in: Client, bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "100"), start_date=date(2026, 10, 5), unit="day")
    run_daily_job(date(2026, 10, 5))
    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))

    run_daily_job(date(2026, 10, 6))

    assert statuses()[:2] == [Occurrence.Status.PAID, Occurrence.Status.DRAFTED]


def test_deleting_a_posted_draft_transaction_reopens_its_occurrence(
    signed_in: Client, bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "25000"))
    run_daily_job(date(2026, 10, 5))
    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))

    signed_in.post(reverse("transaction_delete", args=[Transaction.objects.get().pk]))

    occurrence = Occurrence.objects.get()
    assert (occurrence.status, occurrence.transaction) == (
        Occurrence.Status.UPCOMING,
        None,
    )
    run_daily_job(date(2026, 10, 6))
    assert first_status() == Occurrence.Status.DRAFTED
    assert Draft.objects.get().status == Draft.Status.WAITING


def test_deleting_a_recorded_covering_transaction_reopens_its_occurrence(
    signed_in: Client, bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "25000"))
    record(bank, rent, "25000", date(2026, 10, 5))
    run_daily_job(date(2026, 10, 5))
    assert first_status() == Occurrence.Status.PAID

    signed_in.post(reverse("transaction_delete", args=[Transaction.objects.get().pk]))
    run_daily_job(date(2026, 10, 20))

    assert first_status() == Occurrence.Status.MISSED


def test_a_schedule_with_no_splits_matches_nothing(
    bank: Account, rent: Account
) -> None:
    make_schedule()
    record(bank, rent, "25000", date(2026, 10, 5))

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.DRAFTED


@pytest.mark.parametrize("paid_to", [None, "Someone else"])
def test_a_transaction_for_another_party_does_not_match(
    bank: Account, rent: Account, paid_to: str | None
) -> None:
    make_schedule((bank, rent, "25000"), party=Party.objects.create(name="Landlord"))
    paid_party = Party.objects.create(name=paid_to) if paid_to else None
    record(bank, rent, "25000", date(2026, 10, 5), paid_party)

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.DRAFTED


def test_a_transaction_for_the_schedules_party_matches(
    bank: Account, rent: Account
) -> None:
    landlord = Party.objects.create(name="Landlord")
    make_schedule((bank, rent, "25000"), party=landlord)
    record(bank, rent, "25000", date(2026, 10, 5), landlord)

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.PAID


def test_a_schedule_with_no_party_matches_any_party(
    bank: Account, rent: Account
) -> None:
    make_schedule((bank, rent, "25000"))
    record(
        bank, rent, "25000", date(2026, 10, 5), Party.objects.create(name="Landlord")
    )

    run_daily_job(date(2026, 10, 5))

    assert first_status() == Occurrence.Status.PAID


@pytest.mark.parametrize(
    ("rule", "days_off", "matches"),
    [
        ({"unit": "day"}, 0, True),
        ({"unit": "day"}, 1, False),
        ({"unit": "week"}, 3, True),
        ({"unit": "week"}, 4, False),
        ({"unit": "week"}, -3, True),
        ({"unit": "week"}, -4, False),
        ({"unit": "day", "every": 3}, 1, True),
        ({"unit": "day", "every": 3}, 2, False),
        ({"unit": "week", "every": 2}, 5, True),
        ({"unit": "week", "every": 2}, 6, False),
        ({"unit": "year"}, 5, True),
        ({"unit": "year"}, 6, False),
        ({"cron": "0 0 5 * *", "every": None, "unit": ""}, 5, True),
        ({"cron": "0 0 5 * *", "every": None, "unit": ""}, 6, False),
    ],
)
def test_the_date_window_narrows_with_the_interval(
    bank: Account,
    rent: Account,
    rule: dict[str, object],
    days_off: int,
    *,
    matches: bool,
) -> None:
    make_schedule((bank, rent, "25000"), grace_days=7, **rule)
    on = date(2026, 10, 5) - timedelta(days=days_off)
    record(bank, rent, "25000", on)

    run_daily_job(max(on, date(2026, 10, 5)))

    status = Occurrence.objects.get(due_date=date(2026, 10, 5)).status
    assert (status == Occurrence.Status.PAID) is matches


def split_queries(occurrences: int, bank: Account, rent: Account) -> int:
    for _ in range(occurrences):
        make_schedule((bank, rent, "25000")).occurrences.create(
            due_date=date(2026, 10, 5)
        )
    with CaptureQueriesContext(connection) as queries:
        match_transactions(date(2026, 10, 5))
    return sum("schedules_schedulesplit" in query["sql"] for query in queries)


def test_matching_reads_schedule_splits_once_however_many_occurrences(
    bank: Account, rent: Account
) -> None:
    one = split_queries(1, bank, rent)
    Occurrence.objects.all().delete()

    assert split_queries(5, bank, rent) == one == 1


@pytest.mark.parametrize(
    ("days_overdue", "status"),
    [
        (MATCH_WINDOW.days, Occurrence.Status.PAID),
        (MATCH_WINDOW.days + 1, Occurrence.Status.MISSED),
    ],
)
def test_a_missed_occurrence_is_matched_only_within_the_window(
    bank: Account, rent: Account, days_overdue: int, status: str
) -> None:
    due = date(2026, 10, 5)
    make_schedule((bank, rent, "25000")).occurrences.create(
        due_date=due, status=Occurrence.Status.MISSED
    )
    record(bank, rent, "25000", due)

    match_transactions(due + timedelta(days=days_overdue))

    assert first_status() == status
