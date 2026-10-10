"""The daily storage chart's bars, laid out for an inline SVG.

The CSP blocks inline styles, so bar sizes go into SVG attributes.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from apps.transactions.cloudflare import DailyStorage

HEIGHT = 100
BAR_PITCH = 10
BAR_WIDTH = 8


@dataclass(frozen=True)
class Bar:
    """One day's bar, in viewBox units."""

    day: date
    size: int
    x: int
    y: int
    height: int


@dataclass(frozen=True)
class StorageChart:
    """Bars scaled so the largest day fills the chart's height."""

    bars: list[Bar]
    peak: int
    width: int
    height: int = HEIGHT
    bar_width: int = BAR_WIDTH

    @classmethod
    def of(cls, days: list[DailyStorage]) -> StorageChart:
        """Lay out one bar per day, in the order given."""
        peak = max((day.size for day in days), default=0)
        bars = []
        for index, day in enumerate(days):
            height = round(day.size * HEIGHT / peak) if peak else 0
            bars.append(
                Bar(
                    day=day.day,
                    size=day.size,
                    x=index * BAR_PITCH,
                    y=HEIGHT - height,
                    height=height,
                )
            )
        return cls(bars=bars, peak=peak, width=len(bars) * BAR_PITCH)
