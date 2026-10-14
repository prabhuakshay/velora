"""A Holding row's Price, its date and Price Source, or why it has none."""

from typing import TYPE_CHECKING, Any

from django import template

if TYPE_CHECKING:
    from django.template.context import Context

    from apps.investments.valuation import HoldingRow

register = template.Library()


@register.inclusion_tag("investments/_holding_price.html", takes_context=True)
def holding_price(context: Context, row: HoldingRow) -> dict[str, Any]:
    """Needs the view's price_files, from fetches.latest_files()."""
    source = row.instrument.price_source
    return {
        "user": context.get("user"),
        "row": row,
        "source": source,
        "file": (context.get("price_files") or {}).get(source),
    }
