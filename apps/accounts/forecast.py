"""Forecast: the Balances each Asset and Liability Account is expected to have."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import models
from django.urls import reverse

from apps.accounts.expected import upcoming_due, waiting_drafts
from apps.accounts.models import BALANCE_KINDS, Account
from apps.cards.statements import (
    carried_credit,
    closing_dates,
    due_date,
    estimate,
    previous_closing,
)
from apps.quick_add.models import Draft, DraftSplit
from apps.schedules.estimates import last_paid_amount

if TYPE_CHECKING:
    from apps.schedules.models import ScheduleSplit

DAYS = 30


class Source(models.TextChoices):
    """Where an expected Move comes from."""

    SCHEDULE = "schedule", "Schedule"
    DRAFT = "draft", "Draft"
    CARD = "card", "Card bill"


@dataclass(frozen=True)
class AccountForecast:
    """One Account's expected Balance on each day of the Forecast."""

    account: Account
    balances: list[Decimal]


@dataclass(frozen=True)
class Item:
    """Something expected on a date, linking to where to act on it.

    A None amount is not known yet, shown as ₹?.
    """

    when: date
    label: str
    amount: Decimal | None
    url: str
    account_ids: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Breach:
    """The first day an Account is expected past its Low-Balance Threshold."""

    account: Account
    on: date
    balance: Decimal

    @property
    def owes(self) -> bool:
        """Whether it warns of owing too much rather than having too little."""
        return self.account.owes


@dataclass(frozen=True)
class Move:
    """Money expected to move on a date, and where to act on it.

    Estimated when the amount is a guess: an open amount's last paid amount,
    or a card's Statement Amount so far.
    """

    when: date
    from_account_id: int | None
    to_account_id: int | None
    amount: Decimal
    label: str
    url: str
    source: Source
    estimated: bool = False
    # Left out of a Statement Amount, like their recorded Transactions: a
    # Statement's payment pays an earlier period and a Card EMI's charges are
    # already billed with its installment.
    off_statement: bool = False


@dataclass(frozen=True)
class Forecast:
    """Each Account's expected Balances over the days from the start date."""

    days: list[date]
    accounts: list[AccountForecast]
    amountless: list[Item]
    breaches: list[Breach]
    moves: list[Move]


def _occurrence_moves(start: date, end: date, amountless: list[Item]) -> list[Move]:
    """Upcoming Occurrences; a Drafted one is counted by its Draft instead.

    An open amount is estimated from the last amount paid by the start.
    """
    estimates: dict[int, Decimal | None] = {}
    moves = []
    for due, schedule in upcoming_due(start, end):
        url = reverse("schedule_detail", args=[schedule.pk])
        unknown: set[int] = set()
        for split in schedule.splits.all():
            amount = split.amount
            if amount is None:
                if split.pk not in estimates:
                    estimates[split.pk] = last_paid_amount(split, start)
                amount = estimates[split.pk]
            if amount is None:
                unknown |= _account_ids(split)
                continue
            moves.append(
                Move(
                    due,
                    split.from_account_id,
                    split.to_account_id,
                    amount,
                    str(schedule),
                    url,
                    Source.SCHEDULE,
                    estimated=split.amount is None,
                )
            )
        if unknown:
            amountless.append(Item(due, str(schedule), None, url, frozenset(unknown)))
    return moves


def _account_ids(split: ScheduleSplit | DraftSplit) -> set[int]:
    ends = (split.from_account_id, split.to_account_id)
    return {pk for pk in ends if pk is not None}


def _draft_moves(end: date, amountless: list[Item]) -> list[Move]:
    moves = []
    for draft in waiting_drafts(end):
        splits = list(draft.splits.all())
        url = reverse("draft_edit", args=[draft.pk])
        if unknown := {
            pk for split in splits if split.amount is None for pk in _account_ids(split)
        }:
            amountless.append(
                Item(draft.date, draft.label, None, url, frozenset(unknown))
            )
        off_statement = draft.source in (Draft.Source.STATEMENT, Draft.Source.CARD_EMI)
        moves += [
            Move(
                draft.date,
                split.from_account_id,
                split.to_account_id,
                split.amount,
                draft.label,
                url,
                Source.DRAFT,
                off_statement=off_statement,
            )
            for split in splits
            if split.amount is not None
        ]
    return moves


def _expected_on_card(
    card: Account, start: date, end: date, moves: list[Move]
) -> Decimal:
    """What the expected moves add to the card's Statement Amount for the period."""
    total = Decimal(0)
    for move in moves:
        if move.off_statement or not start <= move.when <= end:
            continue
        if move.from_account_id == card.pk:
            total += move.amount
        elif move.to_account_id == card.pk:
            total -= move.amount
    return total


def _card_moves(start: date, end: date, expected: list[Move]) -> list[Move]:
    """Payments of the Statements not stored yet whose Due Day falls by the end.

    A stored Statement's payment is counted by its Draft, or already recorded.
    Each is estimated from the card's activity in its period so far, plus the
    expected Occurrences and Drafts dated in it, less the credit carried from
    the last stored Statement through the ones before it.
    """
    moves = []
    for card in Account.objects.filter(statement_day__isnull=False):
        last = card.statements.order_by("period_end").last()
        previous = last.period_end if last else None
        credit = carried_credit(card)
        for closing in closing_dates(card, previous or start - timedelta(days=1), end):
            due = due_date(card, closing)
            if due > end:
                break
            period_start = (previous or previous_closing(card, closing)) + timedelta(
                days=1
            )
            raw = estimate(card, period_start, closing, credit).raw + _expected_on_card(
                card, period_start, closing, expected
            )
            amount = max(raw, Decimal(0))
            credit = amount - raw
            if amount > 0:
                moves.append(
                    Move(
                        due,
                        card.pays_from_id,
                        card.pk,
                        amount,
                        f"{card} bill",
                        reverse("account_transactions", args=[card.kind, card.pk]),
                        Source.CARD,
                        estimated=True,
                    )
                )
            previous = closing
    return moves


def _breach(
    account: Account, days: list[date], balances: list[Decimal]
) -> Breach | None:
    """The first day under the threshold, or over it for a Liability.

    A Liability's threshold caps what is owed, so 0 means no warning;
    otherwise every card in debt would warn.
    """
    threshold = account.low_balance_threshold
    owes = account.owes
    if owes and not threshold:
        return None
    for day, balance in zip(days, balances, strict=True):
        if balance > threshold if owes else balance < threshold:
            return Breach(account, day, balance)
    return None


def forecast(start: date, length: int = DAYS) -> Forecast:
    """Each visible Asset and Liability Account's Balance from start for length days."""
    days = [start + timedelta(days=offset) for offset in range(length)]
    accounts = list(
        Account.objects.filter(kind__in=BALANCE_KINDS, hidden=False)
        .with_balance(start)
        .order_by("kind", "name")
    )
    changes: dict[int, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    amountless: list[Item] = []
    moves = [
        *_occurrence_moves(start, days[-1], amountless),
        *_draft_moves(days[-1], amountless),
    ]
    moves += _card_moves(start, days[-1], moves)
    for move in moves:
        # Anything due before the start still to happen lands on the first day.
        when = max(move.when, start)
        if move.to_account_id:
            changes[move.to_account_id][when] += move.amount
        if move.from_account_id:
            changes[move.from_account_id][when] -= move.amount
    rows = []
    breaches = []
    for account in accounts:
        balance = account.balance
        balances = []
        for day in days:
            balance += account.sign * changes[account.pk][day]
            balances.append(balance)
        rows.append(AccountForecast(account, balances))
        if breach := _breach(account, days, balances):
            breaches.append(breach)
    amountless.sort(key=lambda item: item.when)
    breaches.sort(key=lambda breach: breach.on)
    moves.sort(key=lambda move: move.when)
    return Forecast(days, rows, amountless, breaches, moves)
