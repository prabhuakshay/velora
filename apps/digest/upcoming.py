"""What needs the user's attention today, for the digest and the Upcoming panel."""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db.models import Q
from django.urls import reverse

from apps.accounts.forecast import Forecast, Item, forecast
from apps.accounts.models import BALANCE_KINDS, Account
from apps.accounts.reconciling import cash_gaps, cash_valuer
from apps.budgets.warnings import due_warnings, warning_items
from apps.cards.models import Statement
from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from apps.budgets.picture import Row
    from apps.investments.valuation import Valuer

# Days before a card's Due Day it starts showing.
CARD_REMINDER_DAYS = 3
STALE_DRAFT_DAYS = 7
# Days an Account in use may go without a Reconciliation.
RECONCILE_DAYS = 30


@dataclass(frozen=True)
class Section:
    """A titled group of Items, such as Missed Occurrences.

    A section without amounts shows none, not even ₹?.
    """

    title: str
    items: list[Item]
    amounts: bool = True


def reminders(today: date) -> list[Item]:
    """Occurrences within their Schedule's reminder lead days.

    Includes those the daily job already drafted, while their Draft waits,
    linking to the Draft; those past their due date too, until they are Missed.
    """
    occurrences = Occurrence.objects.filter(
        Q(status=Occurrence.Status.UPCOMING, due_date__gte=today)
        | Q(status=Occurrence.Status.DRAFTED, draft__status=Draft.Status.WAITING),
        schedule__active=True,
    ).select_related("schedule__party", "draft")
    return [
        _occurrence_item(occurrence)
        for occurrence in occurrences.prefetch_related("schedule__splits")
        if occurrence.due_date
        <= today + timedelta(days=occurrence.schedule.reminder_days)
    ]


def _occurrence_item(occurrence: Occurrence) -> Item:
    """The Occurrence, linking to its waiting Draft, else its Schedule."""
    return Item(
        occurrence.due_date,
        str(occurrence.schedule),
        occurrence.schedule.amount,
        _waiting_or(
            getattr(occurrence, "draft", None),
            reverse("schedule_detail", args=[occurrence.schedule_id]),
        ),
    )


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
        _occurrence_item(occurrence)
        for occurrence in occurrences.prefetch_related("schedule__splits")
    ]


def card_due_days(today: date) -> list[Item]:
    """Unpaid Statements due within CARD_REMINDER_DAYS, with their payment."""
    statements = (
        Statement.objects.unpaid()
        .filter(
            due_date__range=(today, today + timedelta(days=CARD_REMINDER_DAYS)),
        )
        .select_related("card", "draft")
    )
    return [
        Item(
            statement.due_date,
            str(statement.card),
            statement.owed,
            _waiting_or(
                getattr(statement, "draft", None),
                reverse(
                    "account_transactions",
                    kwargs={"kind": "liability", "pk": statement.card_id},
                ),
            ),
        )
        for statement in statements
        if statement.needs_payment
    ]


def stale_drafts(today: date) -> list[Item]:
    """Drafts left waiting STALE_DRAFT_DAYS or more since they were made.

    Leaves out those another section already shows or will show in time: an
    Occurrence's while Coming up or Missed, and a card payment's before its
    Due Day.
    """
    drafts = (
        Draft.objects.waiting()
        .filter(created_at__date__lte=today - timedelta(days=STALE_DRAFT_DAYS))
        .exclude(occurrence__status=Occurrence.Status.MISSED)
        .exclude(
            occurrence__status=Occurrence.Status.DRAFTED,
            occurrence__schedule__active=True,
        )
        .exclude(statement__due_date__gte=today)
        .select_related("party")
        .prefetch_related("splits")
    )
    return [
        Item(
            draft.date,
            draft.label,
            draft.amount,
            reverse("draft_edit", args=[draft.pk]),
        )
        for draft in drafts
    ]


def low_balances(today: date, outlook: Forecast | None = None) -> list[Item]:
    """Each Account the Forecast expects past its Low-Balance Threshold.

    Dated the first day it is, with the Balance expected then. Reads the
    outlook when given, rather than building today's Forecast again.
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
        for breach in (outlook or forecast(today)).breaches
    ]


def reconcile_due(today: date) -> list[Item]:
    """Each shown Account to reconcile, linking to its Reconcile form.

    Due when it has a Split in the last RECONCILE_DAYS but no Reconciliation
    in them, or whenever its latest Reconciliation no longer matches.
    """
    since = today - timedelta(days=RECONCILE_DAYS)
    accounts = (
        Account.objects.filter(kind__in=BALANCE_KINDS, hidden=False)
        .with_balance()
        .with_latest_reconciliation()
        .with_used(since, today)
        .order_by("name")
    )
    valuer = cash_valuer(accounts)
    due = []
    for account in accounts:
        if not account.offers_reconciliation:
            continue
        _check_cash(account, today, valuer)
        reconciled_on = account.reconciled_on
        unreconciled = account.used and (
            reconciled_on is None or reconciled_on <= since
        )
        if account.off_by or unreconciled:
            due.append(_reconcile_item(account, today))
    return due


def _check_cash(account: Account, today: date, valuer: Valuer) -> None:
    """Make an account that Holds Cash show its Cash and how far off from it."""
    if not account.reconciles_cash:
        return
    reconciled_on = account.reconciled_on
    days = [today] if reconciled_on is None else [today, reconciled_on]
    gaps = cash_gaps(account, days, valuer)
    account.balance -= gaps[today]
    if reconciled_on is not None and account.off_by is not None:
        account.off_by += gaps[reconciled_on]


def _reconcile_item(account: Account, today: date) -> Item:
    """The Account's broken Reconciliation and how far off, else its Balance.

    An account that Holds Cash shows its Cash instead of its Balance.
    """
    url = reverse("account_reconcile", kwargs={"kind": account.kind, "pk": account.pk})
    reconciled_on = account.reconciled_on
    if reconciled_on and account.off_by:
        return Item(
            reconciled_on,
            f"{account}: Reconciliation on {reconciled_on:%-d %b %Y} is off by",
            account.off_by,
            url,
        )
    since = (
        f"not reconciled since {reconciled_on:%-d %b %Y}"
        if reconciled_on
        else "never reconciled"
    )
    label, shown = f"{account}, {since}", account.balance
    # ADR 0009: below zero owed is in credit, shown unsigned like the Balance.
    if account.owes and shown < 0:
        label, shown = f"{label}, in credit", -shown
    return Item(today, label, shown, url)


# In the order they are shown, before Budgets; add a (title, finder) pair for a
# new section.
SECTIONS: tuple[tuple[str, Callable[[date], list[Item]]], ...] = (
    ("Coming up", reminders),
    ("Missed", missed),
    ("Card Due Days", card_due_days),
    ("Low balance", low_balances),
    (f"Drafts waiting {STALE_DRAFT_DAYS} days", stale_drafts),
    ("Reconcile", reconcile_due),
)


def upcoming(
    today: date, warned: list[Row] | None = None, outlook: Forecast | None = None
) -> list[Section]:
    """The sections with something in them.

    Budgets shows the warned Budgets when given, else those due today, so the
    digest can record exactly the warnings it sent. A page that already built
    today's Forecast passes it as outlook.
    """
    if warned is None:
        warned = due_warnings(today)
    sections = [
        Section(
            title,
            low_balances(today, outlook) if find is low_balances else find(today),
        )
        for title, find in SECTIONS
    ]
    sections.append(Section("Budgets", warning_items(warned, today)))
    return [section for section in sections if section.items]
