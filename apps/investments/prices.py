"""Fetching Prices: today's from AMFI and NSE, and past ones held Instruments miss."""

import logging
from collections import defaultdict
from datetime import date, timedelta
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Min, Q
from django.db.models.functions import Least
from django.utils import timezone

from apps.investments.models import Instrument, Price, PriceFetch, PriceSource
from apps.investments.price_source import Amfi, Nse, SourceUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from apps.investments.price_source import PriceRow, Source

logger = logging.getLogger("nightly_prices")

# Read on each run, so tests can swap in fakes.
SOURCES: dict[PriceSource, Source] = {PriceSource.AMFI: Amfi(), PriceSource.NSE: Nse()}
# Keeps each archive request small; AMFI refuses long history ranges.
WINDOW_DAYS = 31
WEEKDAYS = 5


class PriceFetchError(Exception):
    """Some sources could not be fetched; their last known Prices stay."""


def _store(rows: list[PriceRow], fetch: PriceFetch) -> tuple[int, set[str]]:
    """Create Instruments not seen before and add each row's Price.

    Only Instruments whose Price Source is the fetch's get a Price from it.
    An Instrument already known keeps its name and kind, and a day already
    priced keeps its Price, so running twice adds nothing. Each new Price
    carries the Price Fetch that stored it and its source. Returns how many
    Prices were added and the ISINs priced from the rows.
    """
    with transaction.atomic():
        Instrument.objects.bulk_create(
            [Instrument(isin=r.isin, name=r.name, kind=r.kind) for r in rows],
            ignore_conflicts=True,
        )
        ids = {
            i.isin: i.pk
            for i in Instrument.objects.filter(isin__in={r.isin for r in rows})
            if i.price_source == fetch.source
        }
        new = [
            Price(
                instrument_id=ids[r.isin],
                date=r.date,
                price=r.price,
                source=fetch.source,
                fetch=fetch,
            )
            for r in rows
            if r.isin in ids
        ]
        # ignore_conflicts leaves no trace of what was skipped, so count around it.
        stored = Price.objects.filter(
            instrument_id__in=ids.values(), date__in={p.date for p in new}
        )
        before = stored.count()
        Price.objects.bulk_create(new, ignore_conflicts=True)
        return stored.count() - before, {r.isin for r in rows if r.isin in ids}


def _reason(error: Exception, fetch: PriceFetch) -> str:
    """Why a Price Fetch failed, in plain language, from the error."""
    source = fetch.source
    if not isinstance(error, SourceUnavailable):
        return f"unexpected error: {error}"
    if error.reason == SourceUnavailable.Reason.UNREACHABLE:
        return f"{source} couldn't be reached"
    day = (
        f"a day in {fetch.range_start:%-d %b} to {fetch.range_end:%-d %b}"
        if fetch.range_start
        else f"{fetch.day_asked:%-d %b}"
    )
    return f"{source} has no file for {day}"


def _held_isins() -> set[str]:
    held = Instrument.objects.filter(
        Q(events__isnull=False) | Q(merged_into_events__isnull=False)
    )
    return {isin for isin in held.values_list("isin", flat=True) if isin}


def _record(
    source: PriceSource,
    trigger: PriceFetch.Trigger,
    fetches: Iterable[Callable[[], list[PriceRow]]],
    *,
    day_asked: date | None = None,
    days: tuple[date, date] | None = None,
) -> PriceFetch:
    """Run one Price Fetch, store its rows and record how it went.

    It asks for one day, or for a backfill the range of days it fills, in
    one or more fetches. Each fetch's rows are stored as they come, so one
    that fails leaves the others' Prices, and the Price Fetch is Failed.
    """
    range_start, range_end = days or (None, None)
    price_fetch = PriceFetch.objects.create(
        source=source,
        trigger=trigger,
        started_at=timezone.now(),
        day_asked=day_asked,
        range_start=range_start,
        range_end=range_end,
    )
    price_fetch.outcome = PriceFetch.Outcome.OK
    isins: set[str] = set()
    for fetch in fetches:
        try:
            rows = fetch()
        except Exception as error:
            logger.exception("Fetching %s Prices failed", source)
            if price_fetch.outcome == PriceFetch.Outcome.OK:
                price_fetch.outcome = PriceFetch.Outcome.FAILED
                price_fetch.reason = _reason(error, price_fetch)
            continue
        added, priced = _store(rows, price_fetch)
        price_fetch.prices_stored += added
        isins.update(priced)
        if day_asked:
            price_fetch.day_used = max((r.date for r in rows), default=None)
    price_fetch.instruments_priced = len(isins & _held_isins())
    price_fetch.finished_at = timezone.now()
    price_fetch.save()
    return price_fetch


def fetch_today(
    today: date, trigger: PriceFetch.Trigger = PriceFetch.Trigger.NIGHTLY
) -> None:
    """Fetch AMFI's and NSE's Prices for today and store them.

    Each source's run is recorded as a Price Fetch. A source that fails is
    skipped and the others still run; this raises afterwards so the job
    shows as failed, and the next night tries again.
    """
    failed = [
        name
        for name, source in SOURCES.items()
        if _record(
            name, trigger, [partial(source.latest, today)], day_asked=today
        ).outcome
        == PriceFetch.Outcome.FAILED
    ]
    if failed:
        raise PriceFetchError(", ".join(failed))


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
        if days and instrument.isin:
            isins, gaps = missing[instrument.price_source]
            isins[instrument.isin] = instrument.first
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
    source: Source, isins: dict[str, date], start: date, end: date
) -> list[PriceRow]:
    """The window's rows for the ISINs held, from when each was first held."""
    return [
        r
        for r in source.history(start, end)
        if r.isin in isins and r.date >= isins[r.isin]
    ]


def backfill(today: date) -> None:
    """Fetch and store the Prices held Instruments miss, up to today.

    Only weekdays with no Price that no earlier run read are fetched, and a
    stored Price is never replaced, so running again is safe. Each source's
    run is recorded as a Price Fetch over the days it fills; a source with
    nothing missing records none. A failed window is skipped and the rest
    still run and store; this raises afterwards so the job shows as failed.
    """
    failed = []
    missing = _missing(today)
    for name, source in SOURCES.items():
        if name not in missing:
            continue
        isins, days = missing[name]
        price_fetch = _record(
            name,
            PriceFetch.Trigger.BACKFILL,
            [partial(_held_rows, source, isins, *window) for window in _windows(days)],
            days=(min(days), max(days)),
        )
        if price_fetch.outcome == PriceFetch.Outcome.FAILED:
            failed.append(name)
        else:
            _mark_checked(isins, today)
    if failed:
        raise PriceFetchError(", ".join(failed))
