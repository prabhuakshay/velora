"""What the overview's status line says about each fetched Price Source."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Max

from apps.investments.models import Price, PriceFetch, PriceSource

if TYPE_CHECKING:
    from datetime import date

FETCHED = (PriceSource.AMFI, PriceSource.NSE)


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
