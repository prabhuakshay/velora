"""What the overview's status line says about each fetched Price Source."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Max, Q

from apps.investments.models import Instrument, Price, PriceFetch, PriceSource

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
    funds = Q(instrument__kind=Instrument.Kind.MUTUAL_FUND)
    prices = Price.objects.filter(instrument__manual_price=False).filter(
        funds if source == PriceSource.AMFI else ~funds
    )
    latest: date | None = prices.aggregate(latest=Max("date"))["latest"]
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
