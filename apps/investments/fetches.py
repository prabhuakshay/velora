"""What Velora shows about Price Fetches, and how long it keeps them."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from django.db.models import Max
from django.utils import timezone

from apps.investments.models import Price, PriceFetch, PriceSource

if TYPE_CHECKING:
    from datetime import date

    from django.db.models.query import QuerySet

FETCHED = (PriceSource.AMFI, PriceSource.NSE)
KEEP_DAYS = 90


@dataclass(frozen=True)
class SourceStatus:
    """One fetched Price Source: its latest Prices' day and latest Price Fetch."""

    source: PriceSource
    prices_for: date | None
    latest: PriceFetch | None


def _prices_for(source: PriceSource) -> date | None:
    latest: date | None = Price.objects.filter(source=source).aggregate(
        latest=Max("date")
    )["latest"]
    return latest


def statuses() -> list[SourceStatus]:
    """The status of each fetched Price Source, AMFI first."""
    return [
        SourceStatus(
            source=source,
            prices_for=_prices_for(source),
            latest=PriceFetch.objects.filter(source=source).first(),
        )
        for source in FETCHED
    ]


def latest_files() -> dict[PriceSource, date]:
    """The day of the file each fetched source's latest working Price Fetch used."""
    files: dict[PriceSource, date] = {}
    for source in FETCHED:
        fetch = PriceFetch.objects.filter(
            source=source, outcome=PriceFetch.Outcome.OK, day_used__isnull=False
        ).first()
        if fetch and fetch.day_used:
            files[source] = fetch.day_used
    return files


def failed_nightly() -> list[PriceFetch]:
    """Each fetched Price Source's latest nightly Price Fetch, when it failed."""
    latest = (
        PriceFetch.objects.filter(
            source=source, trigger=PriceFetch.Trigger.NIGHTLY
        ).first()
        for source in FETCHED
    )
    return [
        fetch
        for fetch in latest
        if fetch is not None and fetch.outcome == PriceFetch.Outcome.FAILED
    ]


def _cutoff(today: date) -> datetime:
    return timezone.make_aware(
        datetime.combine(today - timedelta(days=KEEP_DAYS), time())
    )


def recent(today: date) -> QuerySet[PriceFetch]:
    """The Price Fetches of the last 90 days, newest first."""
    return PriceFetch.objects.filter(started_at__gte=_cutoff(today))


def remove_old_price_fetches(today: date) -> None:
    """Remove Price Fetches older than 90 days; their Prices stay."""
    PriceFetch.objects.filter(started_at__lt=_cutoff(today)).delete()
