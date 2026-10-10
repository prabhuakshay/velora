"""What Subscriptions cost a month and a year."""

from dataclasses import dataclass
from decimal import Decimal

from apps.schedules.models import Schedule

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

    @property
    def monthly(self) -> Decimal | None:
        """A twelfth of the yearly cost."""
        return None if self.yearly is None else self.yearly / 12


def subscription_costs() -> list[SubscriptionCost]:
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
        costs.append(SubscriptionCost(schedule, yearly))
    return costs
