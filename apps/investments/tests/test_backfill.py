from datetime import date, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING
from urllib.error import URLError

import pytest

from apps.investments.backfill import WINDOW_DAYS, backfill_prices
from apps.investments.models import Instrument, InvestmentEvent, Price
from apps.investments.nightly import PriceFetchError
from apps.investments.tests.conftest import add_price, make_broker, row

if TYPE_CHECKING:
    from apps.investments.price_source import PriceRow
    from apps.investments.tests.conftest import FakePriceSource

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
STOCK = "INE000000002"
# A Monday; the weekend after it is 7 and 8 March.
MONDAY = date(2026, 3, 2)


def day(n: int) -> date:
    return MONDAY + timedelta(days=n)


def buy(isin: str, on: date) -> None:
    InvestmentEvent.objects.create(
        account=make_broker(f"Broker {isin}", opening="10000"),
        instrument=Instrument.objects.get(isin=isin),
        kind="buy",
        date=on,
        units=1,
        amount=10,
    )


def fund(price: str, on: date) -> PriceRow:
    return row(FUND, "Nifty Fund", "mutual_fund", price, on)


def stock(price: str, on: date) -> PriceRow:
    return row(STOCK, "Acme Ltd", "stock", price, on)


def prices(isin: str) -> dict[date, str]:
    return {
        p.date: str(p.price)
        for p in Price.objects.filter(instrument__isin=isin).order_by("date")
    }


@pytest.fixture(autouse=True)
def instruments() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=STOCK, name="Acme Ltd", kind="stock")


def test_backfill_fills_missing_days_from_the_first_buy(
    fake_prices: FakePriceSource,
) -> None:
    buy(FUND, day(2))
    buy(STOCK, day(3))
    add_price(FUND, day(3), "50")
    fake_prices.history = [
        fund("9", day(1)),
        fund("10", day(2)),
        fund("11", day(3)),
        fund("12", day(4)),
        stock("100", day(2)),
        stock("101", day(3)),
        stock("102", day(4)),
    ]

    backfill_prices(today=day(4))

    assert prices(FUND) == {day(2): "10.0000", day(3): "50.0000", day(4): "12.0000"}
    assert prices(STOCK) == {day(3): "101.0000", day(4): "102.0000"}


def test_a_rerun_fetches_only_days_still_missing(fake_prices: FakePriceSource) -> None:
    buy(FUND, day(2))
    fake_prices.history = [fund("10", day(n)) for n in range(2, 5)]
    backfill_prices(today=day(4))
    fake_prices.fetched.clear()

    backfill_prices(today=day(7))

    assert fake_prices.fetched == [("AMFI", day(7), day(7))]
    assert len(prices(FUND)) == 3


def test_weekends_are_not_fetched(fake_prices: FakePriceSource) -> None:
    buy(FUND, day(4))
    add_price(FUND, day(4), "10")

    backfill_prices(today=day(6))

    assert fake_prices.fetched == []


def test_a_long_gap_is_fetched_a_window_at_a_time(
    fake_prices: FakePriceSource,
) -> None:
    buy(FUND, day(0))

    backfill_prices(today=day(70))

    windows = [(start, end) for _, start, end in fake_prices.fetched]
    assert windows[0][0] == day(0)
    assert windows[-1][1] == day(70)
    assert all((end - start).days < WINDOW_DAYS for start, end in windows)
    assert all(later[0] > earlier[1] for earlier, later in pairwise(windows))


def test_a_failed_source_keeps_existing_prices_and_fills_the_other(
    fake_prices: FakePriceSource,
) -> None:
    buy(FUND, day(2))
    buy(STOCK, day(2))
    add_price(FUND, day(2), "50")
    fake_prices.amfi_history = URLError("AMFI is down")
    fake_prices.history = [stock("100", day(2)), stock("101", day(3))]

    with pytest.raises(PriceFetchError, match="AMFI"):
        backfill_prices(today=day(3))

    assert prices(FUND) == {day(2): "50.0000"}
    assert prices(STOCK) == {day(2): "100.0000", day(3): "101.0000"}


def test_instruments_not_held_or_without_an_isin_are_left_alone(
    fake_prices: FakePriceSource,
) -> None:
    Instrument.objects.filter(isin=STOCK).update(isin=None)
    InvestmentEvent.objects.create(
        account=make_broker(opening="10000"),
        instrument=Instrument.objects.get(isin=None),
        kind="buy",
        date=day(2),
        units=1,
        amount=10,
    )
    fake_prices.history = [fund("10", day(2)), stock("100", day(2))]

    backfill_prices(today=day(2))

    assert fake_prices.fetched == []
    assert not Price.objects.exists()


def test_an_instrument_held_through_a_merger_is_backfilled_from_the_merger(
    fake_prices: FakePriceSource,
) -> None:
    new = Instrument.objects.create(isin="INF000000009", name="New", kind="mutual_fund")
    buy(FUND, day(0))
    InvestmentEvent.objects.create(
        account=InvestmentEvent.objects.get().account,
        instrument=Instrument.objects.get(isin=FUND),
        new_instrument=new,
        kind="merger",
        date=day(2),
    )
    fake_prices.history = [
        row("INF000000009", "New", "mutual_fund", "20", day(n)) for n in range(4)
    ]

    backfill_prices(today=day(3))

    assert set(prices("INF000000009")) == {day(2), day(3)}


def test_a_day_with_no_file_is_not_fetched_again(fake_prices: FakePriceSource) -> None:
    buy(FUND, day(0))
    # day(2) is a market holiday: the archive has nothing for it.
    fake_prices.history = [fund("10", day(n)) for n in (0, 1, 3, 4)]
    backfill_prices(today=day(4))
    fake_prices.fetched.clear()

    backfill_prices(today=day(4))

    assert fake_prices.fetched == []


def test_an_instrument_missing_from_the_files_is_not_fetched_again(
    fake_prices: FakePriceSource,
) -> None:
    buy(STOCK, day(0))
    backfill_prices(today=day(4))
    fake_prices.fetched.clear()

    backfill_prices(today=day(7))

    assert fake_prices.fetched == [("NSE", day(4), day(7))]


def test_an_earlier_buy_recorded_later_is_still_backfilled(
    fake_prices: FakePriceSource,
) -> None:
    buy(FUND, day(3))
    fake_prices.history = [fund("10", day(n)) for n in range(5)]
    backfill_prices(today=day(4))

    first = InvestmentEvent.objects.get()
    InvestmentEvent.objects.create(
        account=first.account,
        instrument=first.instrument,
        kind="buy",
        date=day(0),
        units=1,
        amount=10,
    )
    backfill_prices(today=day(4))

    assert set(prices(FUND)) == {day(n) for n in range(5)}


def test_a_failed_source_is_tried_again(fake_prices: FakePriceSource) -> None:
    buy(FUND, day(0))
    fake_prices.amfi_history = URLError("AMFI is down")
    with pytest.raises(PriceFetchError):
        backfill_prices(today=day(4))
    fake_prices.amfi_history = None
    fake_prices.history = [fund("10", day(n)) for n in range(5)]

    backfill_prices(today=day(4))

    assert len(prices(FUND)) == 5
