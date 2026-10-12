"""Chart geometry for inline SVGs, in attributes as the CSP blocks inline styles."""

from dataclasses import dataclass
from decimal import Decimal

WIDTH = 600
HEIGHT = 160
# Bar charts are 100 units tall, so a bar's height reads as a percentage.
BAR_HEIGHT = 100


@dataclass(frozen=True)
class Line:
    """A polyline over the values, the area under it and the zero line if crossed.

    Scaled to the values rather than from 0, so small moves stay visible.
    """

    points: str
    area: str
    zero: float | None
    width: int = WIDTH
    height: int = HEIGHT


def line(values: list[Decimal]) -> Line:
    """Lay the values out left to right across the chart."""
    low, high = min(values), max(values)
    step = WIDTH / max(len(values) - 1, 1)

    def y(value: Decimal) -> float:
        if high == low:
            return HEIGHT / 2
        return float(HEIGHT - (value - low) / (high - low) * HEIGHT)

    points = " ".join(f"{step * i:.1f},{y(v):.1f}" for i, v in enumerate(values))
    return Line(
        points=points,
        area=f"0,{HEIGHT} {points} {WIDTH},{HEIGHT}",
        zero=y(Decimal(0)) if low < 0 < high else None,
    )


@dataclass(frozen=True)
class Bar:
    """One bar's top and height in a chart BAR_HEIGHT tall."""

    y: float
    height: float


def bar(value: Decimal, peak: Decimal) -> Bar:
    """A bar for the value, the peak filling the chart; nothing at or below 0."""
    if value <= 0 or peak <= 0:
        return Bar(BAR_HEIGHT, 0)
    height = float(value / peak * BAR_HEIGHT)
    return Bar(BAR_HEIGHT - height, height)
