"""The nightly Price fetch and the Price backfill as Procrastinate tasks (ADR 0005)."""

from contextlib import suppress

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from procrastinate.contrib.django import app
from procrastinate.exceptions import AlreadyEnqueued

from apps.core.jobs import daily_cron
from apps.investments.backfill import backfill_prices as run_backfill
from apps.investments.nightly import run_nightly_prices

# NSE publishes its bhavcopy in the evening and AMFI its NAVs by 11 pm.
NIGHT_HOUR = 23
BACKFILL_LOCK = "investments.backfill_prices"


@app.periodic(cron=daily_cron(settings.TIME_ZONE, NIGHT_HOUR))
@app.task(name="investments.nightly_prices", queueing_lock="investments.nightly_prices")
def nightly_prices(timestamp: int) -> None:  # noqa: ARG001
    """Fetch and store today's Prices in Velora's time zone."""
    run_nightly_prices(timezone.localdate())


@app.task(name="investments.backfill_prices")
def backfill_prices() -> None:
    """Fill the past Prices held Instruments miss, up to today."""
    run_backfill(timezone.localdate())


def queue_backfill() -> None:
    """Queue a backfill, unless one is already waiting to run."""
    # The savepoint keeps a refused duplicate from aborting the request's transaction.
    with suppress(AlreadyEnqueued), transaction.atomic():
        backfill_prices.configure(queueing_lock=BACKFILL_LOCK).defer()
