import pytest

from apps.investments.models import Instrument, PriceSource


@pytest.mark.parametrize(
    ("kind", "isin", "expected"),
    [
        ("mutual_fund", "INF209K01YM2", PriceSource.AMFI),
        ("stock", "INE002A01018", PriceSource.NSE),
        ("etf", "INF204KB14I2", PriceSource.NSE),
        ("mutual_fund", None, PriceSource.MANUAL),
        ("stock", None, PriceSource.MANUAL),
    ],
)
def test_the_isin_decides_where_prices_come_from(
    kind: str, isin: str | None, expected: PriceSource
) -> None:
    instrument = Instrument(kind=kind, isin=isin)

    assert instrument.price_source == expected
