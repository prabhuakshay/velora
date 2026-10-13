"""The nightly job that keeps every Instrument's Price current."""

import logging
from typing import TYPE_CHECKING

from django.db import transaction

from apps.investments import price_source
from apps.investments.models import Instrument, Price

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

logger = logging.getLogger("nightly_prices")


class PriceFetchError(Exception):
    """Some sources could not be fetched; their last known Prices stay."""


def store(rows: list[price_source.PriceRow]) -> None:
    """Create Instruments not seen before and add each row's Price.

    An Instrument already known keeps its name and kind, and a day already
    priced keeps its Price, so running twice adds nothing.
    """
    with transaction.atomic():
        Instrument.objects.bulk_create(
            [Instrument(isin=r.isin, name=r.name, kind=r.kind) for r in rows],
            ignore_conflicts=True,
        )
        ids = dict(
            Instrument.objects.filter(
                isin__in={r.isin for r in rows}, manual_price=False
            ).values_list("isin", "pk")
        )
        Price.objects.bulk_create(
            [
                Price(instrument_id=ids[r.isin], date=r.date, price=r.price)
                for r in rows
                if r.isin in ids
            ],
            ignore_conflicts=True,
        )


def run_nightly_prices(today: date) -> None:
    """Fetch AMFI's and NSE's Prices for today and store them.

    A source that fails is skipped and the others still run; the job raises
    afterwards so it shows as failed, and the next night tries again.
    """
    sources: dict[str, Callable[[], list[price_source.PriceRow]]] = {
        "AMFI": price_source.amfi_rows,
        "NSE": lambda: price_source.nse_rows(today),
    }
    failed = []
    for name, fetch in sources.items():
        try:
            rows = fetch()
        except Exception:
            logger.exception("Fetching %s Prices failed", name)
            failed.append(name)
            continue
        store(rows)
    if failed:
        raise PriceFetchError(", ".join(failed))
