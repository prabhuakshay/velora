"""Goal Progress: what Allocations count, from their sources' values now.

Pure functions over plain numbers, so the Goal pages and later Projections can
share them without touching the database.

No rupee of a source counts twice: its percentages count first, then each
fixed amount, in the order given, counts only what is still left of it.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Share:
    """An Allocation's share of its source: a percentage or a fixed amount."""

    percent: Decimal | None = None
    amount: Decimal | None = None


@dataclass(frozen=True)
class Counted:
    """What a share counts, and whether it asked for more than was left."""

    amount: Decimal
    capped: bool


def _available(value: Decimal) -> Decimal:
    # A source in the red has nothing to count toward a Goal.
    return max(value, Decimal(0))


def count_shares(value: Decimal, shares: Sequence[Share]) -> list[Counted]:
    """What each share of one source worth value counts, in the shares' order."""
    available = _available(value)
    counted: dict[int, Counted] = {}
    left = available
    for index, share in enumerate(shares):
        if share.percent is not None:
            amount = (available * share.percent / 100).quantize(CENT, ROUND_HALF_UP)
            counted[index] = Counted(amount, capped=False)
            left -= amount
    for index, share in enumerate(shares):
        if share.amount is not None:
            amount = min(share.amount, max(left, Decimal(0)))
            counted[index] = Counted(amount, capped=amount < share.amount)
            left -= amount
    return [counted[index] for index in range(len(shares))]


def unallocated(value: Decimal, shares: Iterable[Share]) -> Decimal:
    """What is left of a source after every Goal's share of it."""
    taken = sum((c.amount for c in count_shares(value, list(shares))), Decimal(0))
    return max(_available(value) - taken, Decimal(0))


def percent_left(shares: Iterable[Share]) -> Decimal:
    """What percentage of a source no Goal has taken by percentage."""
    return 100 - sum((share.percent for share in shares if share.percent), Decimal(0))
