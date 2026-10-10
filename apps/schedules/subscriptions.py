"""What Subscriptions cost a month and a year."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.schedules.models import Schedule

if TYPE_CHECKING:
    from datetime import date

TIMES_A_YEAR = {
    "day": Decimal(365),
    "week": Decimal(52),
    "month": Decimal(12),
    "year": Decimal(1),
}


@dataclass(frozen=True)
class SubscriptionCost:
    """A Subscription and what it costs a year, None while its amount is open."""

    schedule: Schedule
    yearly: Decimal | None
    ended: bool

    @property
    def monthly(self) -> Decimal | None:
        """A twelfth of the yearly cost."""
        return None if self.yearly is None else self.yearly / 12

    @property
    def counted(self) -> bool:
        """Whether it adds to the totals: still paid for, at a known amount."""
        return self.yearly is not None and self.schedule.active and not self.ended


def subscription_costs(today: date) -> list[SubscriptionCost]:
    """Every Subscription with its cost at its current amount."""
    costs = []
    for schedule in Schedule.objects.filter(is_subscription=True).prefetch_related(
        "splits"
    ):
        amount = schedule.amount
        yearly = (
            None
            if amount is None
            else amount * TIMES_A_YEAR[schedule.unit] / schedule.every
        )
        ended = schedule.ends_on is not None and schedule.ends_on < today
        costs.append(SubscriptionCost(schedule, yearly, ended))
    return costs


def yearly_total(costs: list[SubscriptionCost]) -> Decimal:
    """What the Subscriptions still paid for cost a year together."""
    return sum(
        (cost.yearly for cost in costs if cost.counted and cost.yearly), Decimal(0)
    )
