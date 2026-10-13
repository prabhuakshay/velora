"""Velora's Investment Import CSV format, written out (ADR 0013)."""

import csv
from typing import TYPE_CHECKING

from django.http import HttpResponse

from apps.investments.models import InvestmentEvent
from apps.investments.replay import DAY_ORDER, MERGER

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal

COLUMNS = (
    "date",
    "account",
    "isin",
    "instrument_name",
    "type",
    "units",
    "price",
    "amount",
    "charges",
    "new_isin",
    "ref",
    "note",
)

EXAMPLES = (
    ("2024-04-10", "Zerodha", "INE002A01018", "Reliance Industries", "BUY", "10",
     "2900", "29000", "20.50", "", "zerodha-2024-001", "First Buy"),
    ("2024-09-02", "Zerodha", "INE002A01018", "Reliance Industries", "SELL", "4",
     "3000", "12000", "15", "", "zerodha-2024-002", ""),
    ("2024-08-19", "Zerodha", "INE002A01018", "Reliance Industries", "DIVIDEND", "",
     "", "60", "", "", "", ""),
    ("2024-10-28", "Zerodha", "INE002A01018", "Reliance Industries", "STOCK_SPLIT",
     "2", "", "", "", "", "", "1 unit became 2"),
    ("2024-10-28", "Zerodha", "INE002A01018", "Reliance Industries", "BONUS", "6",
     "", "", "", "", "", ""),
    ("2025-01-15", "Kuvera", "INF000000001", "New Fund (name of the new ISIN)",
     "MERGER", "", "", "", "", "INF000000002", "", "Old Fund merged into New Fund"),
)  # fmt: skip


def csv_response(filename: str, rows: Iterable[Iterable[str]]) -> HttpResponse:
    """A CSV download in the import format, the header first."""
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
    writer = csv.writer(response)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return response


def template_csv() -> HttpResponse:
    """The import template: the header and an example row of every type."""
    return csv_response("investment-import-template.csv", EXAMPLES)


def _number(value: Decimal | None) -> str:
    return "" if value is None else f"{value.normalize():f}"


def event_row(event: InvestmentEvent) -> list[str]:
    """The event as an import row; a Merger names its new Instrument."""
    named = event.new_instrument if event.kind == MERGER else event.instrument
    return [
        event.date.isoformat(),
        event.account.name,
        event.instrument.isin,
        named.name if named else "",
        event.kind.upper(),
        _number(event.units),
        _number(event.price),
        _number(event.amount),
        _number(event.charges or None),
        event.new_instrument.isin if event.new_instrument else "",
        event.ref,
        event.note,
    ]


def events_csv() -> HttpResponse:
    """Every Investment Event, in the order an import applies them."""
    events = InvestmentEvent.objects.select_related(
        "account", "instrument", "new_instrument"
    )
    ordered = sorted(
        events, key=lambda event: (event.date, DAY_ORDER.index(event.kind), event.pk)
    )
    return csv_response("investment-events.csv", map(event_row, ordered))
