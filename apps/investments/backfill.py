"""Backfilling the past Prices of every Instrument held, from its first event."""

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING

from django.db.models import Min

from apps.investments import price_source
from apps.investments.models import Instrument, Price
from apps.investments.nightly import PriceFetchError, store

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger("nightly_prices")

# Keeps each archive request small; AMFI refuses long history ranges.
WINDOW_DAYS = 31
WEEKDAYS = 5


def _sources() -> dict[str, Callable[[date, date], list[price_source.PriceRow]]]:
    # Looked up on each run so tests can swap the client's functions.
    return {
        "AMFI": price_source.amfi_history_rows,
        "NSE": price_source.nse_history_rows,
    }


def _source(kind: str) -> str:
    return "AMFI" if kind == Instrument.Kind.MUTUAL_FUND else "NSE"


def _weekdays(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        if day.weekday() < WEEKDAYS:
            yield day
        day += timedelta(days=1)


def _windows(days: set[date]) -> Iterator[tuple[date, date]]:
    """Runs of the days, each spanning fewer than WINDOW_DAYS."""
    ordered = sorted(days)
    start = last = ordered[0]
    for day in ordered[1:]:
        if (day - start).days >= WINDOW_DAYS:
            yield start, last
            start = day
        last = day
    yield start, last


def _missing(today: date) -> dict[str, tuple[set[str], set[date]]]:
    """Per source, the ISINs held and the weekdays some of them have no Price."""
    held = Instrument.objects.filter(manual_price=False, events__isnull=False)
    firsts = {
        pk: (isin, kind, first)
        for pk, isin, kind, first in held.annotate(first=Min("events__date"))
        .values_list("pk", "isin", "kind", "first")
        .distinct()
    }
    priced = set(
        Price.objects.filter(instrument__in=firsts).values_list("instrument", "date")
    )
    missing: dict[str, tuple[set[str], set[date]]] = defaultdict(lambda: (set(), set()))
    for pk, (isin, kind, first) in firsts.items():
        days = {d for d in _weekdays(first, today) if (pk, d) not in priced}
        if days:
            isins, gaps = missing[_source(kind)]
            isins.add(isin)
            gaps.update(days)
    return missing


def backfill_prices(today: date) -> None:
    """Fetch and store the Prices held Instruments miss, up to today.

    Only weekdays with no Price are fetched, and a stored Price is never
    replaced, so running again is safe. A failed fetch is skipped and the
    rest still run; the job raises afterwards so it shows as failed.
    """
    failed = []
    missing = _missing(today)
    for name, fetch in _sources().items():
        if name not in missing:
            continue
        isins, days = missing[name]
        for start, end in _windows(days):
            try:
                rows = fetch(start, end)
            except Exception:
                logger.exception("Backfilling %s Prices failed", name)
                failed.append(name)
                continue
            store([r for r in rows if r.isin in isins])
    if failed:
        raise PriceFetchError(", ".join(sorted(set(failed))))
