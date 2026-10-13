"""Goals with their Allocations valued now, for the Goals list and Goal page."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.goals.models import Allocation
from apps.goals.progress import (
    counted,
    goal_progress,
    is_capped,
    percent_left,
    unallocated,
)
from apps.goals.sources import source_values

if TYPE_CHECKING:
    from collections.abc import Iterable

    from apps.goals.models import Goal


@dataclass(frozen=True)
class Line:
    """One Allocation, what its source is worth and what is left of it."""

    allocation: Allocation
    value: Decimal
    counted: Decimal
    capped: bool
    unallocated: Decimal
    percent_left: Decimal


@dataclass(frozen=True)
class GoalSummary:
    """A Goal and its Allocations as valued now."""

    goal: Goal
    lines: list[Line]

    @property
    def progress(self) -> Decimal:
        """Goal Progress at today's Market Values and Balances."""
        return goal_progress((line.allocation.share, line.value) for line in self.lines)

    @property
    def percent_done(self) -> Decimal:
        """Progress as a percentage of the target, at most 100."""
        done = self.progress / self.goal.target_amount * 100
        return min(done, Decimal(100)).quantize(Decimal("0.1"))

    @property
    def capped(self) -> bool:
        """Whether any fixed amount asks for more than its source is worth."""
        return any(line.capped for line in self.lines)


def summarise(goals: Iterable[Goal]) -> list[GoalSummary]:
    """Value each Goal's Allocations; what's unallocated counts every Goal's."""
    allocations = list(Allocation.objects.select_related("account", "instrument"))
    values = source_values({a.account_id for a in allocations})
    by_source: dict[str, list[Allocation]] = defaultdict(list)
    for allocation in allocations:
        by_source[allocation.source_key].append(allocation)
    by_goal: dict[int, list[Line]] = defaultdict(list)
    for allocation in sorted(allocations, key=lambda a: a.source_label.lower()):
        key = allocation.source_key
        value = values.get(key, Decimal(0))
        shared = by_source[key]
        by_goal[allocation.goal_id].append(
            Line(
                allocation=allocation,
                value=value,
                counted=counted(allocation.share, value),
                capped=is_capped(allocation.share, value),
                unallocated=unallocated(value, (a.share for a in shared)),
                percent_left=percent_left(a.share for a in shared),
            )
        )
    return [GoalSummary(goal, by_goal[goal.pk]) for goal in goals]
