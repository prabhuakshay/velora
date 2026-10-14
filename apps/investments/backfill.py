"""Backfilling the past Prices of every Instrument held, from its first event."""

from collections import defaultdict
from datetime import date, timedelta
from functools import partial
from typing import TYPE_CHECKING, cast

from django.db.models import Min
from django.db.models.functions import Least

from apps.investments import price_source
from apps.investments.models import Instrument, Price, PriceFetch, PriceSource
from apps.investments.nightly import PriceFetchError, record

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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
            if (instrument.pk, d) not in priced and not _checked(instrument, d)
        }
        if days:
            isins, gaps = missing[instrument.price_source]
            isins[cast("str", instrument.isin)] = instrument.first
            gaps.update(days)
    return missing


def _checked(instrument: Instrument, day: date) -> bool:
    start, end = instrument.history_checked_from, instrument.history_checked_until
    return start is not None and end is not None and start <= day <= end


def _mark_checked(isins: dict[str, date], today: date) -> None:
    """Every day before today from first held is now priced or read."""
    # Today's file can still be published later, so it stays unread.
    for isin, first in isins.items():
        Instrument.objects.filter(isin=isin).update(
            history_checked_from=first, history_checked_until=today - timedelta(days=1)
        )


def _held_rows(
    fetch: Callable[[date, date], list[price_source.PriceRow]],
    isins: dict[str, date],
    start: date,
    end: date,
) -> list[price_source.PriceRow]:
    """The window's rows for the ISINs held, from when each was first held."""
    return [r for r in fetch(start, end) if r.isin in isins and r.date >= isins[r.isin]]


def backfill_prices(today: date) -> None:
    """Fetch and store the Prices held Instruments miss, up to today.

    Only weekdays with no Price that no earlier run read are fetched, and a
    stored Price is never replaced, so running again is safe. Each source's
    run is recorded as a Price Fetch over the days it fills; a source with
    nothing missing records none. A failed window is skipped and the rest
    still run and store; the job raises afterwards so it shows as failed.
    """
    failed = []
    missing = _missing(today)
    for name, fetch in _sources().items():
        if name not in missing:
            continue
        isins, days = missing[name]
        price_fetch = record(
            name,
            PriceFetch.Trigger.BACKFILL,
            [partial(_held_rows, fetch, isins, *window) for window in _windows(days)],
            days=(min(days), max(days)),
        )
        if price_fetch.outcome == PriceFetch.Outcome.FAILED:
            failed.append(name)
        else:
            _mark_checked(isins, today)
    if failed:
        raise PriceFetchError(", ".join(failed))
