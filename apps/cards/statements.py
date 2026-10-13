"""Working out each credit card Statement and proposing its payment."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction as db_transaction
from django.db.models import Min, QuerySet, Sum

from apps.accounts.models import Account, AccountKind
from apps.cards.models import Statement
from apps.core.dates import day_of
from apps.core.jobs import run_each
from apps.quick_add.models import Draft, DraftSplit
from apps.schedules.matching import find_cover
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(frozen=True)
class Estimate:
    """What a Statement Amount estimate is made of."""

    spent: Decimal
    paid: Decimal
    card_emis: Decimal
    credit: Decimal = Decimal(0)

    @property
    def raw(self) -> Decimal:
        """The estimate before it is floored, below zero when credit is left."""
        return self.spent - self.paid + self.card_emis - self.credit

    @property
    def amount(self) -> Decimal:
        """The estimate itself, never below zero."""
        return max(self.raw, Decimal(0))


def estimate(
    card: Account, start: date, end: date, credit: Decimal = Decimal(0)
) -> Estimate:
    """What the card's activity from start to end suggests the Statement holds.

    Spends minus payments and refunds to the card, all dated in the period,
    minus the Carried Credit from the Statement before. A payment linked to
    any Statement, even one it does not cover yet, paid for that Statement's
    period, not this one, so it is left out. Each Card EMI swaps its purchase
    for what the bank bills in the period, which already holds the interest,
    GST and fees its posted Drafts record, so those are left out too.
    """
    in_period = Split.objects.filter(transaction__date__range=(start, end))
    spent = (
        in_period.filter(from_account=card)
        .exclude(transaction__draft__card_emi__isnull=False)
        .aggregate(total=Sum("amount"))
    )
    paid = in_period.filter(
        to_account=card, transaction__statement__isnull=True
    ).aggregate(total=Sum("amount"))
    emis = sum(
        (emi.billed(start, end) for emi in card.card_emis.select_related("purchase")),
        Decimal(0),
    )
    return Estimate(
        spent["total"] or Decimal(0), paid["total"] or Decimal(0), emis, credit
    )


def estimate_statement_amount(
    card: Account, start: date, end: date, credit: Decimal = Decimal(0)
) -> Decimal:
    """The Statement Amount the card's activity from start to end suggests."""
    return estimate(card, start, end, credit).amount


@dataclass(frozen=True)
class Credit:
    """The Carried Credit a Statement takes in and what it passes on.

    It passes on how far its own Statement Amount falls below zero, `left`,
    and how far its linked payments go beyond it, `overpaid`.
    """

    taken: Decimal
    left: Decimal
    overpaid: Decimal

    @property
    def carried(self) -> Decimal:
        """The Carried Credit it passes on to the next Statement."""
        return self.left + self.overpaid


def credit_chain(card: Account) -> Iterator[tuple[Statement, Estimate, Credit]]:
    """Each of the card's Statements in period order, estimated now, with its credit.

    The earliest takes no credit. An actual amount from the bank already
    counts any credit, so it stands for the Statement. Otherwise even a paid
    Statement passes on what its estimate now leaves, as its stored amount is
    floored and took the credit it had when paid.
    """
    taken = Decimal(0)
    for statement in card.statements.with_paid():
        parts = estimate(card, statement.period_start, statement.period_end, taken)
        raw = statement.actual_amount
        if raw is None:
            raw = parts.raw
        floored = max(raw, Decimal(0))
        credit = Credit(taken, floored - raw, max(statement.paid - floored, Decimal(0)))
        yield statement, parts, credit
        taken = credit.carried


def carried_credit(card: Account) -> Decimal:
    """The Carried Credit the card's latest Statement passes on."""
    carried = Decimal(0)
    for _statement, _parts, credit in credit_chain(card):
        carried = credit.carried
    return carried


def closing_dates(card: Account, after: date, until: date) -> Iterator[date]:
    """The card's Statement Days after `after`, up to `until`."""
    day: int = card.statement_day  # type: ignore[assignment]
    months = 0
    while (closing := day_of(after.year, after.month + months, day)) <= until:
        if closing > after:
            yield closing
        months += 1


def due_date(card: Account, closing: date) -> date:
    """The first Due Day after the period closes."""
    day: int = card.due_day  # type: ignore[assignment]
    due = day_of(closing.year, closing.month, day)
    return due if due > closing else day_of(closing.year, closing.month + 1, day)


def previous_closing(card: Account, closing: date) -> date:
    """The Statement Day the period before this one closed on."""
    day: int = card.statement_day  # type: ignore[assignment]
    return day_of(closing.year, closing.month - 1, day)


def periods_to_create(card: Account, today: date) -> Iterator[date]:
    """The closing dates of the periods that ended before today with no Statement.

    Spends dated on the Statement Day still belong to its period, so the
    Statement waits for the day after. A card with no Statement starts from its
    latest period, and only while that period's payment is still due.
    """
    yesterday = today - timedelta(days=1)
    last = card.statements.order_by("period_end").last()
    if last:
        yield from closing_dates(card, last.period_end, yesterday)
        return
    # Any two months hold a Statement Day, however the month ends clamp it.
    latest = max(
        closing_dates(card, yesterday - timedelta(days=62), yesterday), default=None
    )
    if latest and due_date(card, latest) >= today:
        yield latest


def propose_payment(statement: Statement) -> None:
    """Propose paying what is still owed from the card's Pays from Account."""
    card = statement.card
    draft = Draft.objects.create(
        source=Draft.Source.STATEMENT,
        statement=statement,
        date=statement.due_date,
        description=str(statement),
        estimated=statement.actual_amount is None,
    )
    DraftSplit.objects.create(
        draft=draft,
        from_account=card.pays_from,
        to_account=card,
        amount=statement.owed,
    )


@db_transaction.atomic
def create_statement(card: Account, closing: date) -> None:
    """Store the Statement for the period closing then, and propose its payment.

    The period starts the day after the last Statement's, so changing the
    Statement Day leaves no gap.
    """
    last = card.statements.order_by("period_end").last()
    after = last.period_end if last else previous_closing(card, closing)
    start = after + timedelta(days=1)
    statement = Statement.objects.create(
        card=card,
        period_start=start,
        period_end=closing,
        due_date=due_date(card, closing),
        estimated_amount=estimate_statement_amount(
            card, start, closing, carried_credit(card)
        ),
    )
    if payment := find_payment(statement):
        link_payment(statement, payment)
    else:
        sync_payment_draft(statement)


def create_statements(today: date) -> None:
    """Create every card's Statements for the periods that ended before today."""

    def create_due(card: Account) -> None:
        for closing in periods_to_create(card, today):
            create_statement(card, closing)

    run_each(
        "create_statements",
        Account.objects.filter(statement_day__isnull=False),
        create_due,
    )


@dataclass
class PaymentLeg:
    """The payment a Statement expects, as matching reads it."""

    from_account: Account
    to_account: Account
    amount: Decimal | None


def find_payment(statement: Statement) -> Transaction | None:
    """A recorded payment of what is still owed between its close and due date.

    Smaller part payments are left for the user to link.
    """
    card = statement.card
    if statement.owed <= 0:
        return None
    return find_cover(
        [PaymentLeg(card.pays_from, card, statement.owed)],  # type: ignore[arg-type]
        statement.due_date,
        Transaction.objects.filter(occurrence__isnull=True, statement__isnull=True),
        earliest=statement.period_end + timedelta(days=1),
    )


@db_transaction.atomic
def link_payment(statement: Statement, transaction: Transaction) -> None:
    """Link the payment to the Statement, which is paid once its payments cover it.

    Its waiting payment Draft takes what is still owed, or is withdrawn.
    """
    statement.add_payment(transaction)
    # Linking re-estimated the card, this Statement included.
    statement.refresh_from_db()
    sync_payment_draft(statement)


def payment_candidates(statement: Statement, today: date) -> QuerySet[Transaction]:
    """The recorded payments into the card the user can link to the Statement.

    Any Asset Account may pay it, of any amount, as long as the payment is
    dated after the period closed and pays no Statement yet. Each carries the
    Account it came from and the amount it paid into the card.
    """
    # The Sums reuse the filter's join, so they add up only the paying Splits.
    return Transaction.objects.filter(
        splits__to_account=statement.card,
        splits__from_account__kind=AccountKind.ASSET,
        occurrence__isnull=True,
        statement__isnull=True,
        date__range=(statement.period_end + timedelta(days=1), today),
    ).annotate(
        paid=Sum("splits__amount"),
        paid_from=Min("splits__from_account__name"),
    )


def match_card_payments(today: date) -> None:
    """Link a recorded payment to each unpaid Statement it covers the rest of."""
    unpaid = (
        Statement.objects.unpaid()
        .filter(
            period_end__lt=today,
            card__pays_from__isnull=False,
        )
        .select_related("card")
    )

    def link_if_covered(statement: Statement) -> None:
        # Settling an earlier Statement re-estimates this one.
        statement.refresh_from_db()
        if payment := find_payment(statement):
            link_payment(statement, payment)

    run_each("match_card_payments", unpaid, link_if_covered)


@db_transaction.atomic
def unlink_payment(statement: Statement, transaction: Transaction) -> None:
    """Unlink one payment from the Statement, leaving it as recorded.

    The Statement is unpaid again once the rest no longer cover it. If the
    payment is the one its own Draft posted, that Draft goes, so it can be
    proposed again for what is still owed.
    """
    statement.remove_payment(transaction)
    Draft.objects.filter(statement=statement, transaction=transaction).delete()
    # The payment counts in the period it is dated in again.
    refresh_estimates(statement.card)
    # Refreshing leaves out a Statement the actual amount has just paid.
    statement.refresh_from_db()
    sync_payment_draft(statement)


def sync_payment_draft(statement: Statement) -> None:
    """Bring the Statement's payment Draft in line with what is still owed.

    A waiting Draft takes what is owed, an estimate until the actual amount is
    entered, or is withdrawn when nothing is; with none proposed yet, one is
    now if something is owed. A posted or rejected Draft is left alone, so no
    second one is proposed.
    """
    draft = Draft.objects.filter(statement=statement).first()
    if draft is None:
        if statement.needs_payment:
            propose_payment(statement)
    elif draft.status == Draft.Status.WAITING:
        if statement.needs_payment:
            draft.splits.filter(to_account=statement.card).update(amount=statement.owed)
            draft.estimated = statement.actual_amount is None
            draft.save(update_fields=["estimated"])
        else:
            draft.delete()


@db_transaction.atomic
def enter_actual_amount(statement: Statement, amount: Decimal | None) -> None:
    """Save the actual Statement Amount, or clear it, and update its payment.

    It changes the credit carried to every later Statement, so the card is
    re-estimated too.
    """
    statement.actual_amount = amount
    statement.save(update_fields=["actual_amount"])
    refresh_estimates(statement.card)
    # Refreshing leaves out a Statement the actual amount has just paid.
    statement.refresh_from_db()
    sync_payment_draft(statement)


@db_transaction.atomic
def refresh_estimates(*accounts: Account) -> None:
    """Re-estimate the unpaid Statements of each Account that is a card.

    Any change to a card's Splits, Card EMIs, linked payments or actual
    amounts can change what an earlier period's estimate comes to, and the
    credit it carries to every later one. A paid Statement is history.
    """
    for account in accounts:
        if not account.is_card:
            continue
        for statement, parts, _credit in credit_chain(account):
            if statement.is_paid:
                continue
            statement.estimated_amount = parts.amount
            statement.save(update_fields=["estimated_amount"])
            sync_payment_draft(statement)
