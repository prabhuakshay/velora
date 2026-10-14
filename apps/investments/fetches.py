"""What Velora shows about Price Fetches, and how long it keeps them."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from django.db.models import Max
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.investments.models import Price, PriceFetch, PriceSource

if TYPE_CHECKING:
    from datetime import date

    from django.db.models.query import QuerySet

FETCHED = (PriceSource.AMFI, PriceSource.NSE)
KEEP_DAYS = 90
DAILY = (PriceFetch.Trigger.NIGHTLY, PriceFetch.Trigger.REFRESH)


@dataclass(frozen=True)
class SourceStatus:
    """One fetched Price Source: its latest Prices' day and latest Price Fetches.

    The status line shows the latest Nightly or Refresh result, and a newer
    Backfill as a note beside it, so a Refresh's own result outlasts the
    Backfill it starts. The banner follows the latest Price Fetch of any kind.
    """

    source: PriceSource
    prices_for: date | None
    latest: PriceFetch | None
    shown: PriceFetch | None
    backfill: PriceFetch | None
    fetching: bool = False

    @property
    def failed(self) -> bool:
        """Whether the latest Price Fetch of any kind failed."""
        return (
            self.latest is not None and self.latest.outcome == PriceFetch.Outcome.FAILED
        )

    @property
    def visible(self) -> bool:
        """A source with no Prices only shows while it is fetching or failing."""
        return bool(self.prices_for) or self.fetching or self.failed

    @property
    def new_prices(self) -> int:
        """Prices stored by the shown Price Fetch and the Backfill after it."""
        return sum(f.prices_stored for f in (self.shown, self.backfill) if f)

    @property
    def not_out_yet(self) -> date | None:
        """The day asked for when NSE fell back to an earlier file."""
        fetch = self.shown
        if (
            fetch
            and fetch.day_used
            and fetch.day_asked
            and fetch.day_used < fetch.day_asked
        ):
            return fetch.day_asked
        return None


def latest_per_source(**filters: object) -> dict[PriceSource, PriceFetch]:
    """Each fetched Price Source's newest Price Fetch matching the filters."""
    fetches = {}
    for source in FETCHED:
        fetch = PriceFetch.objects.filter(source=source, **filters).first()
        if fetch is not None:
            fetches[source] = fetch
    return fetches


def _prices_for(source: PriceSource) -> date | None:
    latest: date | None = Price.objects.filter(source=source).aggregate(
        latest=Max("date")
    )["latest"]
    return latest


def _refresh_jobs(*states: str) -> bool:
    return ProcrastinateJob.objects.filter(
        task_name="investments.refresh_prices", status__in=states
    ).exists()


def statuses(*, waiting: bool) -> list[SourceStatus]:
    """The status of each fetched Price Source, AMFI first.

    A source is fetching while its latest Price Fetch runs or a Refresh waits
    to start.
    """
    latest = latest_per_source()
    daily = latest_per_source(trigger__in=DAILY)
    backfills = latest_per_source(trigger=PriceFetch.Trigger.BACKFILL)
    result = []
    for source in FETCHED:
        fetch = latest.get(source)
        shown = daily.get(source) or backfills.get(source)
        backfill = backfills.get(source)
        result.append(
            SourceStatus(
                source=source,
                prices_for=_prices_for(source),
                latest=fetch,
                shown=shown,
                backfill=backfill
                if shown and backfill and backfill.started_at > shown.started_at
                else None,
                fetching=waiting
                or (fetch is not None and fetch.outcome == PriceFetch.Outcome.RUNNING),
            )
        )
    return result


def status_line() -> dict[str, object]:
    """The status line's context: it polls until no Price Fetch is in flight."""
    waiting = refresh_waiting()
    sources = statuses(waiting=waiting)
    return {
        "price_statuses": sources,
        "refresh_waiting": waiting,
        "today": timezone.localdate(),
        "price_shown": any(s.visible for s in sources),
        "price_polling": any(s.fetching for s in sources)
        or _refresh_jobs("todo", "doing"),
    }


def refresh_waiting() -> bool:
    """Whether a Refresh is queued and not yet started."""
    return _refresh_jobs("todo")


def latest_files() -> dict[PriceSource, date]:
    """The day of the file each fetched source's latest working Price Fetch used."""
    return {
        source: fetch.day_used
        for source, fetch in latest_per_source(
            outcome=PriceFetch.Outcome.OK, day_used__isnull=False
        ).items()
        if fetch.day_used
    }


def failed_nightly() -> list[PriceFetch]:
    """Each fetched Price Source's latest nightly Price Fetch, when it failed."""
    return [
        fetch
        for fetch in latest_per_source(trigger=PriceFetch.Trigger.NIGHTLY).values()
        if fetch.outcome == PriceFetch.Outcome.FAILED
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
