"""What needs the user's attention today, for the digest and the Upcoming panel."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Q
from django.urls import reverse

from apps.accounts.forecast import forecast
from apps.cards.models import Statement
from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

# Days before a card's Due Day it starts showing.
CARD_REMINDER_DAYS = 3
STALE_DRAFT_DAYS = 7


@dataclass(frozen=True)
class Item:
    """One thing to act on; a None amount is not known yet."""

    when: date
    label: str
    amount: Decimal | None
    url: str


@dataclass(frozen=True)
class Section:
    """A titled group of Items, such as Missed Occurrences."""

    title: str
    items: list[Item]


def reminders(today: date) -> list[Item]:
    """Occurrences within their Schedule's reminder lead days.

    Includes those due today the daily job already drafted, while their Draft
    waits, linking to the Draft.
    """
    occurrences = Occurrence.objects.filter(
        Q(status=Occurrence.Status.UPCOMING)
        | Q(status=Occurrence.Status.DRAFTED, draft__status=Draft.Status.WAITING),
        due_date__gte=today,
        schedule__active=True,
    ).select_related("schedule__party", "draft")
    return [
        Item(
            occurrence.due_date,
            str(occurrence.schedule),
            occurrence.schedule.amount,
            _waiting_or(
                getattr(occurrence, "draft", None),
                reverse("schedule_detail", args=[occurrence.schedule_id]),
            ),
        )
        for occurrence in occurrences.prefetch_related("schedule__splits")
        if occurrence.due_date
        <= today + timedelta(days=occurrence.schedule.reminder_days)
    ]


def _waiting_or(draft: Draft | None, fallback: str) -> str:
    """The waiting Draft to post or reject, else the fallback page."""
    if draft and draft.status == Draft.Status.WAITING:
        return reverse("draft_edit", args=[draft.pk])
    return fallback


def missed(today: date) -> list[Item]:  # noqa: ARG001
    """Every Missed Occurrence, until a Transaction covers it or it is Skipped."""
    occurrences = Occurrence.objects.filter(
        status=Occurrence.Status.MISSED
    ).select_related("schedule__party", "draft")
    return [
        Item(
            occurrence.due_date,
            str(occurrence.schedule),
            occurrence.schedule.amount,
            _waiting_or(
                getattr(occurrence, "draft", None),
                reverse("schedule_detail", args=[occurrence.schedule_id]),
            ),
        )
        for occurrence in occurrences.prefetch_related("schedule__splits")
    ]


def card_due_days(today: date) -> list[Item]:
    """Unpaid Statements due within CARD_REMINDER_DAYS, with their payment."""
    statements = Statement.objects.filter(
        transaction__isnull=True,
        due_date__range=(today, today + timedelta(days=CARD_REMINDER_DAYS)),
    ).select_related("card", "draft")
    return [
        Item(
            statement.due_date,
            str(statement.card),
            statement.amount,
            _waiting_or(
                getattr(statement, "draft", None),
                reverse(
                    "account_transactions",
                    kwargs={"kind": "liability", "pk": statement.card_id},
                ),
            ),
        )
        for statement in statements
        if statement.amount > 0
    ]


def _draft_amount(draft: Draft) -> Decimal | None:
    amounts = [split.amount for split in draft.splits.all()]
    known = [amount for amount in amounts if amount is not None]
    if not amounts or len(known) < len(amounts):
        return None
    return sum(known, Decimal(0))


def stale_drafts(today: date) -> list[Item]:
    """Drafts left waiting STALE_DRAFT_DAYS or more since they were made.

    Leaves out those another section already shows or will show in time: a
    Missed Occurrence's, and a card payment's before its Due Day.
    """
    drafts = (
        Draft.objects.waiting()
        .filter(created_at__date__lte=today - timedelta(days=STALE_DRAFT_DAYS))
        .exclude(occurrence__status=Occurrence.Status.MISSED)
        .exclude(statement__due_date__gte=today)
        .select_related("party")
        .prefetch_related("splits")
    )
    return [
        Item(
            draft.date,
            draft.description or str(draft.party or draft.new_party_name or draft),
            _draft_amount(draft),
            reverse("draft_edit", args=[draft.pk]),
        )
        for draft in drafts
    ]


def low_balances(today: date) -> list[Item]:
    """Each Account the Forecast expects past its Low-Balance Threshold.

    Dated the first day it is, with the Balance expected then.
    """
    return [
        Item(
            breach.on,
            f"{breach.account} owing over its limit"
            if breach.owes
            else str(breach.account),
            breach.balance,
            reverse("forecast"),
        )
        for breach in forecast(today).breaches
    ]


# In the order they are shown; add a (title, finder) pair for a new section.
SECTIONS: tuple[tuple[str, Callable[[date], list[Item]]], ...] = (
    ("Coming up", reminders),
    ("Missed", missed),
    ("Card Due Days", card_due_days),
    ("Low balance", low_balances),
    ("Drafts waiting 7 days", stale_drafts),
)


def upcoming(today: date) -> list[Section]:
    """The sections with something in them."""
    sections = [Section(title, find(today)) for title, find in SECTIONS]
    return [section for section in sections if section.items]
