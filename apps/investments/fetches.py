"""What the overview's status line says about each fetched Price Source."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Max, Q
from procrastinate.contrib.django.models import ProcrastinateJob

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
