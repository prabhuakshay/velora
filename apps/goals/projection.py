"""A Goal's Projection, inflated target and Required Monthly Investment.

Pure functions over plain numbers. Growth is monthly at the rate equivalent to
the Goal's expected yearly return, and money added each month is added at the
month's end.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from apps.core.dates import months_after
from apps.goals.progress import CENT

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date


@dataclass(frozen=True)
class Contribution:
    """A linked Schedule's monthly-equivalent amount and how many months it lasts."""

    monthly: Decimal
    months: int


def months_between(start: date, end: date) -> int:
    """The whole months from start to end, 0 if end is not after start."""
    months = (end.year - start.year) * 12 + end.month - start.month
    if months_after(start, months) > end:
        months -= 1
    return max(months, 0)


def _paise(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def inflated_target(target: Decimal, inflation: Decimal, months: int) -> Decimal:
    """The target in money of the target date, at the yearly inflation %."""
    return _paise(target * (1 + inflation / 100) ** (Decimal(months) / 12))


def monthly_rate(expected_return: Decimal) -> Decimal:
    """The monthly rate that compounds to the expected yearly return %."""
    return (1 + expected_return / 100) ** (Decimal(1) / 12) - 1


def _annuity(monthly: Decimal, rate: Decimal, months: int) -> Decimal:
    if not rate:
        return monthly * months
    return monthly * ((1 + rate) ** months - 1) / rate


def projection(
    progress: Decimal,
    rate: Decimal,
    months: int,
    contributions: Iterable[Contribution],
) -> Decimal:
    """Progress grown for months, plus what each Contribution adds by then."""
    total = progress * (1 + rate) ** months
    for contribution in contributions:
        paying = min(contribution.months, months)
        added = _annuity(contribution.monthly, rate, paying)
        total += added * (1 + rate) ** (months - paying)
    return _paise(total)


def required_monthly(gap: Decimal, rate: Decimal, months: int) -> Decimal:
    """The monthly amount that grows to the gap in months; 0 with no gap."""
    if gap <= 0:
        return Decimal(0)
    if months == 0:
        return gap
    return _paise(gap / _annuity(Decimal(1), rate, months))
