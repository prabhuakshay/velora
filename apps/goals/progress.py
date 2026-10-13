"""Goal Progress: what Allocations count, from their sources' values now.

Pure functions over plain numbers, so the Goal pages and later Projections can
share them without touching the database.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Share:
    """An Allocation's share of its source: a percentage or a fixed amount."""

    percent: Decimal | None = None
    amount: Decimal | None = None


def _available(value: Decimal) -> Decimal:
    # A source in the red has nothing to count toward a Goal.
    return max(value, Decimal(0))


def counted(share: Share, value: Decimal) -> Decimal:
    """What the share counts of a source worth value, never more than it holds."""
    available = _available(value)
    if share.percent is not None:
        return (available * share.percent / 100).quantize(CENT, ROUND_HALF_UP)
    return min(share.amount or Decimal(0), available)


def is_capped(share: Share, value: Decimal) -> bool:
    """Whether a fixed amount asks for more than its source is worth."""
    return share.amount is not None and share.amount > _available(value)


def goal_progress(allocations: Iterable[tuple[Share, Decimal]]) -> Decimal:
    """Goal Progress: the sum of what each (share, source value) counts."""
    return sum((counted(share, value) for share, value in allocations), Decimal(0))


def unallocated(value: Decimal, shares: Iterable[Share]) -> Decimal:
    """What is left of a source after every Goal's share of it."""
    taken = sum((counted(share, value) for share in shares), Decimal(0))
    return max(_available(value) - taken, Decimal(0))


def percent_left(shares: Iterable[Share]) -> Decimal:
    """What percentage of a source no Goal has taken by percentage."""
    return 100 - sum((share.percent for share in shares if share.percent), Decimal(0))
