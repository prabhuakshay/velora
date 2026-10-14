"""Backfilling the past Prices of every Instrument held, from its first event."""

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING

from django.db.models import Min
from django.db.models.functions import Least

from apps.investments import price_source
from apps.investments.models import Instrument, Price, PriceSource
from apps.investments.nightly import PriceFetchError, store

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger("nightly_prices")

# Keeps each archive request small; AMFI refuses long history ranges.
WINDOW_DAYS = 31
WEEKDAYS = 5


def _sources() -> dict[
    PriceSource, Callable[[date, date], list[price_source.PriceRow]]
]:
    # Looked up on each run so tests can swap the client's functions.
    return {
        PriceSource.AMFI: price_source.amfi_history_rows,
        PriceSource.NSE: price_source.nse_history_rows,
    }


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


def _missing(today: date) -> dict[PriceSource, tuple[dict[str, date], set[date]]]:
    """Per source, each ISIN held from when, and the weekdays some have no Price."""
    # An Instrument a Merger turns Lots into is held from the Merger's date.
    held = [
        i
        for i in Instrument.objects.annotate(
            first=Least(Min("events__date"), Min("merged_into_events__date"))
        ).filter(first__isnull=False)
        if i.price_source != PriceSource.MANUAL
    ]
    priced = set(
        Price.objects.filter(instrument__in=held).values_list("instrument", "date")
    )
    missing: dict[PriceSource, tuple[dict[str, date], set[date]]] = defaultdict(
        lambda: ({}, set())
    )
    for instrument in held:
        days = {
            d
            for d in _weekdays(instrument.first, today)
            if (instrument.pk, d) not in priced
        }
        if days:
            isins, gaps = missing[instrument.price_source]
            isins[instrument.isin] = instrument.first
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
            store([r for r in rows if r.isin in isins and r.date >= isins[r.isin]])
    if failed:
        raise PriceFetchError(", ".join(sorted(set(failed))))
