"""Forecast: the Balances each Asset and Liability Account is expected to have."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from apps.accounts.models import BALANCE_KINDS, Account, AccountKind
from apps.cards.statements import (
    closing_dates,
    due_date,
    estimate_statement_amount,
    previous_closing,
)
from apps.quick_add.models import Draft
from apps.schedules.estimates import last_paid_amount
from apps.schedules.models import Occurrence

DAYS = 30


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


@dataclass(frozen=True)
class Breach:
    """The first day an Account is expected past its Low-Balance Threshold."""

    account: Account
    on: date
    balance: Decimal

    @property
    def owes(self) -> bool:
        """Whether it warns of owing too much rather than having too little."""
        return self.account.kind == AccountKind.LIABILITY


@dataclass(frozen=True)
class Forecast:
    """Each Account's expected Balances over the days from the start date."""

    days: list[date]
    accounts: list[AccountForecast]
    amountless: list[Item]
    breaches: list[Breach]


@dataclass(frozen=True)
class _Move:
    when: date
    from_account_id: int | None
    to_account_id: int | None
    amount: Decimal
    # Left out of a Statement Amount, like their recorded Transactions: a
    # Statement's payment pays an earlier period and a Card EMI's charges are
    # already billed with its installment.
    off_statement: bool = False


def _occurrence_moves(start: date, end: date, amountless: list[Item]) -> list[_Move]:
    """Upcoming Occurrences; a Drafted one is counted by its Draft instead.

    An open amount is estimated from the last amount paid by the start.
    """
    occurrences = (
        Occurrence.objects.filter(
            status=Occurrence.Status.UPCOMING,
            schedule__active=True,
            due_date__lte=end,
        )
        .select_related("schedule__party")
        .prefetch_related("schedule__splits")
    )
    estimates: dict[int, Decimal | None] = {}
    moves = []
    for occurrence in occurrences:
        schedule = occurrence.schedule
        unknown = False
        for split in schedule.splits.all():
            amount = split.amount
            if amount is None:
                if split.pk not in estimates:
                    estimates[split.pk] = last_paid_amount(split, start)
                amount = estimates[split.pk]
            if amount is None:
                unknown = True
                continue
            moves.append(
                _Move(
                    occurrence.due_date,
                    split.from_account_id,
                    split.to_account_id,
                    amount,
                )
            )
        if unknown:
            amountless.append(
                Item(
                    occurrence.due_date,
                    str(schedule),
                    None,
                    reverse("schedule_detail", args=[schedule.pk]),
                )
            )
    return moves


def _draft_moves(end: date, amountless: list[Item]) -> list[_Move]:
    drafts = (
        Draft.objects.waiting()
        .filter(date__lte=end)
        .select_related("party")
        .prefetch_related("splits")
    )
    moves = []
    for draft in drafts:
        splits = list(draft.splits.all())
        if any(split.amount is None for split in splits):
            amountless.append(
                Item(
                    draft.date,
                    draft.label,
                    None,
                    reverse("draft_edit", args=[draft.pk]),
                )
            )
        off_statement = draft.source in (Draft.Source.STATEMENT, Draft.Source.CARD_EMI)
        moves += [
            _Move(
                draft.date,
                split.from_account_id,
                split.to_account_id,
                split.amount,
                off_statement,
            )
            for split in splits
            if split.amount is not None
        ]
    return moves


def _expected_on_card(
    card: Account, start: date, end: date, moves: list[_Move]
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


def _card_moves(start: date, end: date, expected: list[_Move]) -> list[_Move]:
    """Payments of the Statements not stored yet whose Due Day falls by the end.

    A stored Statement's payment is counted by its Draft, or already recorded.
    Each is estimated from the card's activity in its period so far, plus the
    expected Occurrences and Drafts dated in it.
    """
    moves = []
    for card in Account.objects.filter(statement_day__isnull=False):
        last = card.statements.order_by("period_end").last()
        previous = last.period_end if last else None
        for closing in closing_dates(card, previous or start - timedelta(days=1), end):
            due = due_date(card, closing)
            if due > end:
                break
            period_start = (previous or previous_closing(card, closing)) + timedelta(
                days=1
            )
            amount = estimate_statement_amount(
                card, period_start, closing
            ) + _expected_on_card(card, period_start, closing, expected)
            if amount > 0:
                moves.append(_Move(due, card.pays_from_id, card.pk, amount))
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
    owes = account.kind == AccountKind.LIABILITY
    if owes and not threshold:
        return None
    for day, balance in zip(days, balances, strict=True):
        if balance > threshold if owes else balance < threshold:
            return Breach(account, day, balance)
    return None


def forecast(start: date) -> Forecast:
    """Each visible Asset and Liability Account's Balance from start for DAYS days."""
    days = [start + timedelta(days=offset) for offset in range(DAYS)]
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
        # A Liability's Balance is what is owed, so money moving in lowers it.
        sign = -1 if account.kind == AccountKind.LIABILITY else 1
        balance = account.balance
        balances = []
        for day in days:
            balance += sign * changes[account.pk][day]
            balances.append(balance)
        rows.append(AccountForecast(account, balances))
        if breach := _breach(account, days, balances):
            breaches.append(breach)
    amountless.sort(key=lambda item: item.when)
    breaches.sort(key=lambda breach: breach.on)
    return Forecast(days, rows, amountless, breaches)
