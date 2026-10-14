"""What Velora shows about Price Fetches, and how long it keeps them."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from django.db.models import Max, Q
from django.utils import timezone

from apps.investments.models import Instrument, Price, PriceFetch, PriceSource

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
