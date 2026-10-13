"""XIRR: the yearly return that explains dated cash flows."""

import math
from decimal import Decimal
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import date

type Flow = tuple[date, Decimal]

DAYS_A_YEAR = 365.0
# Yearly rates tried in turn to find one bracket the answer lies in; near -100%
# and very high rates are far apart, so the steps widen away from zero.
TRIES = (-0.9999, -0.99, -0.9, -0.5, 0.0, 0.5, 1.0, 3.0, 10.0, 100.0, 1000.0)
STEPS = 200


def xirr(flows: Iterable[Flow]) -> Decimal | None:
    """The yearly rate, as a percentage, at which the flows are worth nothing.

    Money out is negative and money in positive. None when there is no such
    rate or the flows span less than one day.
    """
    listed = sorted(flows)
    if not listed:
        return None
    amounts = [amount for _, amount in listed]
    if listed[0][0] == listed[-1][0] or min(amounts) >= 0 or max(amounts) <= 0:
        return None
    start = listed[0][0]
    timed = [
        ((day - start).days / DAYS_A_YEAR, float(amount)) for day, amount in listed
    ]

    def worth(rate: float) -> float:
        return math.fsum(amount / (1 + rate) ** years for years, amount in timed)

    for low, high in pairwise(TRIES):
        if worth(low) * worth(high) <= 0:
            return Decimal(f"{_bisect(worth, low, high) * 100:.6f}")
    return None


def returns(flows: Iterable[Flow], value: Decimal, today: date) -> Decimal | None:
    """XIRR of the flows, with what is still held counted as sold for value today."""
    return xirr([*flows, (today, value)])


def _bisect(worth: Callable[[float], float], low: float, high: float) -> float:
    low_sign = worth(low) > 0
    for _ in range(STEPS):
        middle = (low + high) / 2
        if (worth(middle) > 0) == low_sign:
            low = middle
        else:
            high = middle
    return (low + high) / 2
