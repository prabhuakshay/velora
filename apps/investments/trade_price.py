"""Trade Price: what one unit of a Buy or Sell changed hands at (ADR 0016).

It is never stored: it is the Amount divided by the units.
"""

from decimal import Decimal

PLACES = Decimal("0.0001")
TOLERANCE_RUPEES = Decimal(1)
TOLERANCE_SHARE = Decimal("0.001")


def trade_price(units: Decimal | None, amount: Decimal | None) -> Decimal | None:
    """The Amount over the units, to 4 decimals; None without both above 0."""
    if not units or not amount or units <= 0 or amount <= 0:
        return None
    return (amount / units).quantize(PLACES)


def agrees(units: Decimal, price: Decimal, amount: Decimal) -> bool:
    """Whether a stated price agrees with the units and Amount.

    Prices are published to 4 decimals and units rounded to 3, so units times
    the price rarely gives the Amount to the paisa. The Trade Price itself
    always agrees, so an exported file re-imports even when its rounding to
    4 decimals drifts past the tolerance over many cheap units.
    """
    if price == trade_price(units, amount):
        return True
    return abs(units * price - amount) <= max(
        TOLERANCE_RUPEES, amount * TOLERANCE_SHARE
    )
