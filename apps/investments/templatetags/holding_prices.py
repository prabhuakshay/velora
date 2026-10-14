"""A Holding row's Price, its date and Price Source, or why it has none."""

from typing import TYPE_CHECKING, Any

from django import template

from apps.investments.models import PriceSource

if TYPE_CHECKING:
    from datetime import date

    from django.template.context import Context

    from apps.investments.valuation import HoldingRow

register = template.Library()


@register.inclusion_tag("investments/_holding_price.html", takes_context=True)
def holding_price(
    context: Context, row: HoldingRow, files: dict[PriceSource, date]
) -> dict[str, Any]:
    """Files is fetches.latest_files(), to name the file a missing Price wasn't in.

    The context only lends the user, whom the price tag needs for Privacy Mode.
    """
    source = row.instrument.price_source
    return {
        "user": context.get("user"),
        "row": row,
        "source": source,
        "manual": source == PriceSource.MANUAL,
        "file": files.get(source),
    }
