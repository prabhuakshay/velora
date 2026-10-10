"""What Subscriptions cost a month and a year, and how their amount changed."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from itertools import takewhile
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.core.dates import months_after
from apps.schedules.models import Schedule, ScheduleSplit
from apps.schedules.repeat import cron_dates

if TYPE_CHECKING:
    from datetime import date

TIMES_A_YEAR: dict[str, Decimal] = {
    Schedule.Unit.DAY: Decimal(365),
    Schedule.Unit.WEEK: Decimal(52),
    Schedule.Unit.MONTH: Decimal(12),
    Schedule.Unit.YEAR: Decimal(1),
}

type PriceHistory = list[tuple[date, Decimal | None]]


@dataclass(frozen=True)
class SubscriptionCost:
    """A Subscription and what it costs a year, None while its amount is open."""

    schedule: Schedule
    yearly: Decimal | None
    ended: bool
    # Each amount it has had, from the day it took effect, oldest first.
    price_history: PriceHistory

    @property
    def monthly(self) -> Decimal | None:
        """A twelfth of the yearly cost."""
        return None if self.yearly is None else self.yearly / 12

    @property
    def counted(self) -> bool:
        """Whether it adds to the totals: still paid for, at a known amount."""
        return self.yearly is not None and self.schedule.active and not self.ended


def _price_histories(schedule_ids: list[int]) -> dict[int, PriceHistory]:
    """Each Schedule's amount at the end of every day its Splits changed.

    Saving the form writes one Split at a time, so only a day's last total is
    kept; the in-between totals were never a real price.
    """
    splits: dict[int, dict[int, Decimal | None]] = defaultdict(dict)
    by_day: dict[int, dict[date, Decimal | None]] = defaultdict(dict)
    records = ScheduleSplit.history.filter(schedule_id__in=schedule_ids).order_by(
        "history_date", "history_id"
    )
    for record in records:
        amounts = splits[record.schedule_id]
        if record.history_type == "-":
            amounts.pop(record.id, None)
        else:
            amounts[record.id] = record.amount
        known = [amount for amount in amounts.values() if amount is not None]
        total = sum(known, Decimal(0)) if len(known) == len(amounts) else None
        by_day[record.schedule_id][timezone.localdate(record.history_date)] = total
    histories: dict[int, PriceHistory] = {}
    for schedule_id, days in by_day.items():
        history = histories[schedule_id] = []
        for day, total in days.items():
            if not history or history[-1][1] != total:
                history.append((day, total))
    return histories


def _times_a_year(schedule: Schedule, today: date) -> Decimal:
    """How often it falls due a year; a cron rule's count for the coming year."""
    if not schedule.cron:
        return TIMES_A_YEAR[schedule.unit] / (schedule.every or 1)
    year_on = months_after(today, 12)
    return Decimal(
        sum(
            1
            for _ in takewhile(
                lambda due: due < year_on, cron_dates(schedule.cron, today)
            )
        )
    )


def subscription_costs(today: date) -> list[SubscriptionCost]:
    """Every Subscription with its cost at its current amount."""
    schedules = list(
        Schedule.objects.filter(is_subscription=True).prefetch_related("splits")
    )
    histories = _price_histories([schedule.pk for schedule in schedules])
    costs = []
    for schedule in schedules:
        amount = schedule.amount
        yearly = None if amount is None else amount * _times_a_year(schedule, today)
        ended = schedule.ends_on is not None and schedule.ends_on < today
        history = histories.get(schedule.pk, [])
        costs.append(SubscriptionCost(schedule, yearly, ended, history))
    return costs


def yearly_total(costs: list[SubscriptionCost]) -> Decimal:
    """What the Subscriptions still paid for cost a year together."""
    return sum(
        (cost.yearly for cost in costs if cost.counted and cost.yearly), Decimal(0)
    )
