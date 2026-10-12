"""The bar that shows a Budget's Spent, with Expected as a lighter extension."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django import template

if TYPE_CHECKING:
    from django.template.context import Context

register = template.Library()

WHOLE = Decimal(100)


def _share(part: Decimal, budget: Decimal) -> Decimal:
    if budget <= 0:
        return WHOLE if part > 0 else Decimal(0)
    return min(max(part / budget * WHOLE, Decimal(0)), WHOLE)


@register.inclusion_tag("budgets/_bar.html", takes_context=True)
def budget_bar(  # noqa: PLR0913
    context: Context,
    budget: Decimal,
    spent: Decimal,
    expected: Decimal | None,
    state: str,
    *,
    thick: bool = False,
) -> dict[str, Any]:
    """Spent and Expected as shares of the Budget, with today's mark this month."""
    spent_share = _share(spent, budget)
    expected_share = min(_share(expected or Decimal(0), budget), WHOLE - spent_share)
    return {
        "user": context.get("user"),
        "pace": context.get("pace"),
        "spent": spent_share,
        "expected": expected_share,
        "state": state,
        "thick": thick,
    }
