"""The nightly Price fetch, the Price backfill and a refresh as Procrastinate tasks.

See ADR 0005.
"""

from contextlib import suppress
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from apps.core.jobs import daily_cron
from apps.investments.models import PriceFetch
from apps.investments.prices import PriceFetchError, backfill, fetch_today

if TYPE_CHECKING:
    from collections.abc import Callable

    from procrastinate.tasks import Task

# NSE publishes its bhavcopy in the evening and AMFI its NAVs by 11 pm.
NIGHT_HOUR = 23
BACKFILL_LOCK = "investments.backfill_prices"
REFRESH_LOCK = "investments.refresh_prices"


@app.periodic(cron=daily_cron(settings.TIME_ZONE, NIGHT_HOUR))
@app.task(name="investments.nightly_prices", queueing_lock="investments.nightly_prices")
def nightly_prices(timestamp: int) -> None:  # noqa: ARG001
    """Fetch and store today's Prices in Velora's time zone."""
    fetch_today(timezone.localdate())


@app.task(name="investments.backfill_prices")
def backfill_prices() -> None:
    """Fill the past Prices held Instruments miss, up to today."""
    backfill(timezone.localdate())


def _queue_once(task: Task[..., None, ...], lock: str) -> bool:
    """Queue the task, unless one is already waiting to run; say if it queued."""
    # The savepoint keeps a refused duplicate from aborting the request's transaction.
    with suppress(AlreadyEnqueued), transaction.atomic():
        task.configure(queueing_lock=lock).defer()
        return True
    return False


def queue_backfill() -> None:
    """Queue a backfill, unless one is already waiting to run."""
    _queue_once(backfill_prices, BACKFILL_LOCK)


@app.task(name="investments.refresh_prices")
def refresh_prices() -> None:
    """Fetch today's Prices, then fill past ones, as the user asked."""
    today = timezone.localdate()
    failed = []
    steps: tuple[Callable[[], None], ...] = (
        lambda: fetch_today(today, PriceFetch.Trigger.REFRESH),
        lambda: backfill(today),
    )
    for step in steps:
        try:
            step()
        except PriceFetchError as error:
            failed.append(str(error))
    if failed:
        raise PriceFetchError(", ".join(failed))


def queue_refresh() -> bool:
    """Queue a refresh, unless one is already waiting to run; say if it queued."""
    return _queue_once(refresh_prices, REFRESH_LOCK)
