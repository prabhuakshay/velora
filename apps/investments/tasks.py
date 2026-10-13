"""The nightly Price fetch as a Procrastinate periodic task (ADR 0005)."""

from django.conf import settings
from django.utils import timezone
from procrastinate.contrib.django import app

from apps.core.jobs import daily_cron
from apps.investments.nightly import run_nightly_prices

# NSE publishes its bhavcopy in the evening and AMFI its NAVs by 11 pm.
NIGHT_HOUR = 23


@app.periodic(cron=daily_cron(settings.TIME_ZONE, NIGHT_HOUR))
@app.task(name="investments.nightly_prices", queueing_lock="investments.nightly_prices")
def nightly_prices(timestamp: int) -> None:  # noqa: ARG001
    """Fetch and store today's Prices in Velora's time zone."""
    run_nightly_prices(timezone.localdate())
