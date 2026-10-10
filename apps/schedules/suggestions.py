"""Noticing steady repeated payments and offering them as Suggested Schedules."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from django.db import transaction as db_transaction
from django.db.models import Sum

from apps.schedules.models import Schedule, SuggestedSchedule
from apps.schedules.repeat import months_after
from apps.transactions.models import Split

Unit = Schedule.Unit

# How many days a payment may land either side of its expected date.
TOLERANCE_DAYS: dict[str, int] = {Unit.WEEK: 1, Unit.MONTH: 3, Unit.YEAR: 10}
MIN_PAYMENTS = 3
AMOUNT_TOLERANCE = Decimal("0.15")


@dataclass(frozen=True)
class Payment:
    """One Transaction's total between a pair of Accounts."""

    transaction_id: int
    date: date
    amount: Decimal


def next_expected(when: date, unit: str) -> date:
    """When the next payment is expected, one `unit` after `when`."""
    match unit:
        case Unit.WEEK:
            return when + timedelta(weeks=1)
        case Unit.MONTH:
            return months_after(when, 1)
        case _:
            return months_after(when, 12)


def steady_run(payments: list[Payment], unit: str) -> list[Payment]:
    """The latest payments that each land within tolerance of the one before."""
    run = [payments[-1]]
    for earlier in reversed(payments[:-1]):
        drift = abs((run[0].date - next_expected(earlier.date, unit)).days)
        if drift > TOLERANCE_DAYS[unit]:
            break
        run.insert(0, earlier)
    return run


def is_stale(latest: Payment, unit: str, today: date) -> bool:
    """Whether the next payment after the latest is overdue beyond tolerance."""
    deadline = next_expected(latest.date, unit) + timedelta(days=TOLERANCE_DAYS[unit])
    return today > deadline


def typical_amount(run: list[Payment]) -> Decimal | None:
    """The median amount, if every payment is within tolerance of it."""
    middle = median(payment.amount for payment in run)
    if all(abs(p.amount - middle) <= middle * AMOUNT_TOLERANCE for p in run):
        return middle.quantize(Decimal("0.01"))
    return None


def payments_by_party_and_accounts(
    today: date,
) -> dict[tuple[int, int, int], list[Payment]]:
    """Every payment to a Party up to today, oldest first, by Party and Accounts."""
    rows = (
        Split.objects.filter(
            transaction__party__isnull=False, transaction__date__lte=today
        )
        .values(
            "transaction__party",
            "from_account",
            "to_account",
            "transaction",
            "transaction__date",
        )
        .annotate(total=Sum("amount"))
        .order_by("transaction__date", "transaction")
    )
    groups: dict[tuple[int, int, int], list[Payment]] = defaultdict(list)
    for row in rows:
        key = (row["transaction__party"], row["from_account"], row["to_account"])
        groups[key].append(
            Payment(row["transaction"], row["transaction__date"], row["total"])
        )
    return groups


def already_known(party: int, source: int, destination: int, unit: str) -> bool:
    """Whether a Schedule covers it or it was suggested before, whatever came of it."""
    covered = Schedule.objects.filter(
        party=party, splits__from_account=source, splits__to_account=destination
    ).exists()
    return (
        covered
        or SuggestedSchedule.objects.filter(
            party=party, from_account=source, to_account=destination, unit=unit
        ).exists()
    )


@db_transaction.atomic
def suggest_schedules(today: date) -> None:
    """Offer each steady repeated payment nothing covers as a Suggested Schedule."""
    for (party, source, destination), payments in payments_by_party_and_accounts(
        today
    ).items():
        for unit in TOLERANCE_DAYS:
            run = steady_run(payments, unit)
            if len(run) < MIN_PAYMENTS or is_stale(run[-1], unit, today):
                continue
            amount = typical_amount(run)
            if amount is None or already_known(party, source, destination, unit):
                continue
            suggestion = SuggestedSchedule.objects.create(
                party_id=party,
                from_account_id=source,
                to_account_id=destination,
                amount=amount,
                unit=unit,
            )
            suggestion.evidence.set(payment.transaction_id for payment in run)
