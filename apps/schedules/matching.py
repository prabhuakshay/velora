"""Recognising Transactions the user recorded as covering expected money."""

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

from django.db import transaction as db_transaction

from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence, Schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet

    from apps.accounts.models import Account

DATE_TOLERANCE = timedelta(days=5)
COVER_AMOUNT_TOLERANCE = Decimal("0.10")


class Leg(Protocol):
    """Money expected to move between two Accounts; None matches any amount."""

    from_account: Account
    to_account: Account
    amount: Decimal | None


def find_cover(
    legs: Iterable[Leg],
    due_date: date,
    candidates: QuerySet[Transaction],
    earliest: date | None = None,
    tolerance: timedelta = DATE_TOLERANCE,
) -> Transaction | None:
    """The candidate nearest the due date with a matching Split for every leg.

    It must fall within `tolerance` of the due date, or from `earliest` when
    given. With no legs, nothing matches.
    """
    legs = list(legs)
    if not legs:
        return None
    matches = candidates.filter(
        date__range=(earliest or due_date - tolerance, due_date + tolerance)
    )
    for leg in legs:
        splits: dict[str, object] = {
            "from_account": leg.from_account,
            "to_account": leg.to_account,
        }
        if leg.amount is not None:
            splits["amount__range"] = (
                leg.amount * (1 - COVER_AMOUNT_TOLERANCE),
                leg.amount * (1 + COVER_AMOUNT_TOLERANCE),
            )
        matches = matches.filter(**{f"splits__{k}": v for k, v in splits.items()})
    return min(
        matches.distinct(),
        key=lambda match: (abs(match.date - due_date), match.pk),
        default=None,
    )


@db_transaction.atomic
def cover(occurrence: Occurrence, transaction: Transaction) -> None:
    """Mark the Occurrence Paid by the Transaction and withdraw its Draft."""
    Draft.objects.waiting().filter(occurrence=occurrence).delete()
    occurrence.settle(transaction)


def match_transactions(today: date) -> None:
    """Cover each open Occurrence a recorded Transaction could already cover."""
    open_occurrences = Occurrence.objects.filter(
        status__in=[
            Occurrence.Status.UPCOMING,
            Occurrence.Status.DRAFTED,
            Occurrence.Status.MISSED,
        ],
        due_date__lte=today + DATE_TOLERANCE,
    ).select_related("schedule")
    for occurrence in open_occurrences:
        match_occurrence(occurrence)


def date_tolerance(schedule: Schedule) -> timedelta:
    """How far from a due date a Transaction may fall and still cover it.

    Under half the interval, so a Transaction can't cover the next Occurrence.
    """
    days: dict[str, int] = {Schedule.Unit.DAY: 1, Schedule.Unit.WEEK: 7}
    days_per_unit = days.get(schedule.unit)
    if days_per_unit is None or schedule.every is None:
        return DATE_TOLERANCE
    return min(
        DATE_TOLERANCE, timedelta(days=(days_per_unit * schedule.every - 1) // 2)
    )


def match_occurrence(occurrence: Occurrence) -> bool:
    """Cover the Occurrence with a recorded Transaction, if one could.

    When the Schedule has a Party, the Transaction must be for it.
    """
    schedule = occurrence.schedule
    candidates = Transaction.objects.filter(
        occurrence__isnull=True, statement__isnull=True
    )
    if schedule.party_id:
        candidates = candidates.filter(party_id=schedule.party_id)
    transaction = find_cover(
        schedule.splits.all(),
        occurrence.due_date,
        candidates,
        tolerance=date_tolerance(schedule),
    )
    if transaction:
        cover(occurrence, transaction)
    return transaction is not None


def mark_missed(today: date) -> None:
    """Mark Missed each Occurrence still uncovered after its grace period."""
    missed = Occurrence.objects.filter(
        status__in=[Occurrence.Status.UPCOMING, Occurrence.Status.DRAFTED],
        due_date__lt=today,
    ).select_related("schedule")
    Occurrence.objects.filter(
        pk__in=[
            occurrence.pk
            for occurrence in missed
            if occurrence.due_date + timedelta(days=occurrence.schedule.grace_days)
            < today
        ]
    ).update(status=Occurrence.Status.MISSED)
