"""What the Schedules pages sum up: money due soon and each Schedule's record."""

import itertools
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Count, Sum

from apps.schedules.models import Occurrence, Schedule
from apps.schedules.repeat import due_dates
from apps.schedules.subscriptions import times_a_year
from apps.transactions.models import Split

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class Flow:
    """Money moved by some due dates: out and in apart, Transfers in neither."""

    due: int = 0
    out: Decimal = Decimal(0)
    income: Decimal = Decimal(0)
    # Due dates with an open amount, which add to neither sum.
    open: int = 0

    def add(self, schedule: Schedule, times: Decimal = Decimal(1)) -> None:
        """Count one due date of the Schedule, or `times` of them."""
        self.due += 1
        amount = schedule.amount
        if amount is None:
            self.open += 1
        elif schedule.is_income:
            self.income += amount * times
        elif not schedule.is_transfer:
            self.out += amount * times


def coming_up(occurrences: Iterable[Occurrence], until: date) -> Flow:
    """What the Occurrences due by `until` move."""
    flow = Flow()
    for occurrence in occurrences:
        if occurrence.due_date <= until:
            flow.add(occurrence.schedule)
    return flow


def a_month(schedules: Iterable[Schedule], today: date) -> Flow:
    """What the Schedules move in an average month, counting each Schedule once."""
    flow = Flow()
    for schedule in schedules:
        flow.add(schedule, times_a_year(schedule, today) / 12)
    return flow


@dataclass(frozen=True)
class Record:
    """How a Schedule's past Occurrences went."""

    counts: dict[str, int]
    # What the Transactions covering its Paid Occurrences moved together.
    paid_total: Decimal

    @property
    def paid(self) -> int:
        """How many Occurrences were Paid."""
        return self.counts.get(Occurrence.Status.PAID, 0)

    @property
    def average(self) -> Decimal | None:
        """The mean amount paid, None until something is paid."""
        return self.paid_total / self.paid if self.paid else None


def record(schedule: Schedule) -> Record:
    """Its Occurrences counted by status, and what was paid in all."""
    counts = dict(
        schedule.occurrences.values_list("status")
        .annotate(n=Count("pk"))
        .values_list("status", "n")
    )
    paid_total = Split.objects.filter(
        transaction__occurrence__schedule=schedule
    ).aggregate(total=Sum("amount"))["total"]
    return Record(counts, paid_total or Decimal(0))


def later_due_dates(schedule: Schedule, today: date, count: int = 3) -> list[date]:
    """The next due dates after the stored Occurrences, for a Schedule still on."""
    if not schedule.active or schedule.has_ended(today):
        return []
    last = schedule.occurrences.order_by("due_date").last()
    since = max(today, last.due_date + timedelta(days=1)) if last else today
    # Ten years on, so a rule that stops matching cannot keep the search going.
    until = today + timedelta(days=3650)
    return list(itertools.islice(due_dates(schedule, since, until), count))


def final_due_date(schedule: Schedule) -> date | None:
    """The last due date, when the rule stops on its own."""
    if schedule.ends_after is None:
        return schedule.ends_on
    dates = list(due_dates(schedule, schedule.start_date, schedule.ends_on or date.max))
    return dates[-1] if dates else None


def due_dates_left(schedule: Schedule, today: date, final: date) -> int:
    """How many due dates fall from today to the final one."""
    return sum(1 for _ in due_dates(schedule, today, final))
