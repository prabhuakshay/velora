"""What Velora shows about Price Fetches, and how long it keeps them."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from django.db.models import Max, Q
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

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
    fetching: bool = False


def _prices_for(source: PriceSource) -> date | None:
    funds = Q(instrument__kind=Instrument.Kind.MUTUAL_FUND)
    prices = Price.objects.filter(instrument__manual_price=False).filter(
        funds if source == PriceSource.AMFI else ~funds
    )
    latest: date | None = prices.aggregate(latest=Max("date"))["latest"]
    return latest


def _refresh_jobs(*states: str) -> bool:
    return ProcrastinateJob.objects.filter(
        task_name="investments.refresh_prices", status__in=states
    ).exists()


def statuses() -> list[SourceStatus]:
    """The status of each fetched Price Source, AMFI first.

    A source is fetching while its latest Price Fetch runs or a Refresh waits
    to start.
    """
    waiting = refresh_waiting()
    result = []
    for source in FETCHED:
        latest = PriceFetch.objects.filter(source=source).first()
        running = latest is not None and latest.outcome == PriceFetch.Outcome.RUNNING
        result.append(
            SourceStatus(
                source=source,
                prices_for=_prices_for(source),
                latest=latest,
                fetching=waiting or running,
            )
        )
    return result


def status_line() -> dict[str, object]:
    """The status line's context: it polls until no Price Fetch is in flight."""
    sources = statuses()
    return {
        "price_statuses": sources,
        "refresh_waiting": refresh_waiting(),
        "price_polling": any(s.fetching for s in sources)
        or _refresh_jobs("todo", "doing"),
    }


def refresh_waiting() -> bool:
    """Whether a Refresh is queued and not yet started."""
    return _refresh_jobs("todo")


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
