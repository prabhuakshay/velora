import pytest

from apps.investments.models import Instrument, PriceSource


@pytest.mark.parametrize(
    ("kind", "manual_price", "expected"),
    [
        ("mutual_fund", False, PriceSource.AMFI),
        ("stock", False, PriceSource.NSE),
        ("etf", False, PriceSource.NSE),
        ("mutual_fund", True, PriceSource.MANUAL),
        ("stock", True, PriceSource.MANUAL),
    ],
)
def test_instrument_knows_where_its_prices_come_from(
    kind: str, *, manual_price: bool, expected: PriceSource
) -> None:
    instrument = Instrument(kind=kind, manual_price=manual_price)

    assert instrument.price_source == expected
