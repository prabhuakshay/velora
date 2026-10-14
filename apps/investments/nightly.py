"""The nightly job that keeps every Instrument's Price current."""

import logging
import urllib.error
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.investments import price_source
from apps.investments.models import Instrument, Price, PriceFetch, PriceSource

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

logger = logging.getLogger("nightly_prices")

NOT_FOUND = 404


class PriceFetchError(Exception):
    """Some sources could not be fetched; their last known Prices stay."""


def store(rows: list[price_source.PriceRow]) -> int:
    """Create Instruments not seen before and add each row's Price.

    An Instrument already known keeps its name and kind, and a day already
    priced keeps its Price, so running twice adds nothing. Returns how many
    Prices were added.
    """
    with transaction.atomic():
        Instrument.objects.bulk_create(
            [Instrument(isin=r.isin, name=r.name, kind=r.kind) for r in rows],
            ignore_conflicts=True,
        )
        ids = dict(
            Instrument.objects.filter(
                isin__in={r.isin for r in rows}, manual_price=False
            ).values_list("isin", "pk")
        )
        new = [
            Price(instrument_id=ids[r.isin], date=r.date, price=r.price)
            for r in rows
            if r.isin in ids
        ]
        # ignore_conflicts leaves no trace of what was skipped, so count around it.
        stored = Price.objects.filter(
            instrument_id__in=ids.values(), date__in={p.date for p in new}
        )
        before = stored.count()
        Price.objects.bulk_create(new, ignore_conflicts=True)
        return stored.count() - before


def reason(error: Exception, source: str, day: date | None) -> str:
    """Why a Price Fetch failed, in plain language, from the error's type."""
    if isinstance(error, urllib.error.HTTPError) and error.code == NOT_FOUND:
        return (
            f"{source} has no file for {day:%-d %b}" if day else f"{source} has no file"
        )
    if isinstance(error, (urllib.error.URLError, TimeoutError)):
        return f"{source} couldn't be reached"
    return f"unexpected error: {error}"


def _held_isins() -> set[str]:
    return set(
        Instrument.objects.filter(
            Q(events__isnull=False) | Q(merged_into_events__isnull=False)
        ).values_list("isin", flat=True)
    )


def record(
    source: PriceSource,
    trigger: PriceFetch.Trigger,
    fetch: Callable[[], list[price_source.PriceRow]],
    *,
    day_asked: date,
) -> PriceFetch:
    """Run one Price Fetch, store its rows and record how it went."""
    price_fetch = PriceFetch.objects.create(
        source=source, trigger=trigger, started_at=timezone.now(), day_asked=day_asked
    )
    try:
        rows = fetch()
    except Exception as error:
        logger.exception("Fetching %s Prices failed", source)
        price_fetch.outcome = PriceFetch.Outcome.FAILED
        price_fetch.reason = reason(error, source, day_asked)
    else:
        price_fetch.prices_stored = store(rows)
        price_fetch.instruments_priced = len({r.isin for r in rows} & _held_isins())
        price_fetch.day_used = max((r.date for r in rows), default=None)
        price_fetch.outcome = PriceFetch.Outcome.OK
    price_fetch.finished_at = timezone.now()
    price_fetch.save()
    return price_fetch


def run_nightly_prices(
    today: date, trigger: PriceFetch.Trigger = PriceFetch.Trigger.NIGHTLY
) -> None:
    """Fetch AMFI's and NSE's Prices for today and store them.

    Each source's run is recorded as a Price Fetch. A source that fails is
    skipped and the others still run; the job raises afterwards so it shows
    as failed, and the next night tries again.
    """
    sources: dict[PriceSource, Callable[[], list[price_source.PriceRow]]] = {
        PriceSource.AMFI: price_source.amfi_rows,
        PriceSource.NSE: lambda: price_source.nse_rows(today),
    }
    failed = [
        source
        for source, fetch in sources.items()
        if record(source, trigger, fetch, day_asked=today).outcome
        == PriceFetch.Outcome.FAILED
    ]
    if failed:
        raise PriceFetchError(", ".join(failed))
