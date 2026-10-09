"""Show amounts in the signed-in user's Number Format."""

from typing import TYPE_CHECKING

from django import template
from django.utils.safestring import SafeString, mark_safe

from apps.users.models import NumberFormat

if TYPE_CHECKING:
    from decimal import Decimal

    from django.template.context import Context

register = template.Library()

MASK: SafeString = mark_safe('<span role="img" aria-label="Amount hidden">₹••••</span>')


def _group(digits: str, number_format: NumberFormat) -> str:
    if number_format == NumberFormat.INTERNATIONAL:
        return f"{int(digits):,}"
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([*groups, tail])


@register.simple_tag(takes_context=True)
def amount(context: Context, value: Decimal) -> str:
    """The value with ₹, its sign and two decimals, grouped by Number Format.

    Under Privacy Mode, a fixed mask instead, so no real value reaches the HTML.
    """
    user = context.get("user")
    if getattr(user, "privacy_mode", False):
        return MASK
    number_format = getattr(user, "number_format", NumberFormat.INDIAN)
    digits, cents = f"{abs(value):.2f}".split(".")
    sign = "-" if value < 0 else ""
    return f"{sign}₹{_group(digits, number_format)}.{cents}"


@register.simple_tag(takes_context=True)
def amount_color(context: Context, value: Decimal) -> str:
    """The class that shows a negative amount in red.

    Nothing under Privacy Mode, where red would give away the sign.
    """
    if value < 0 and not getattr(context.get("user"), "privacy_mode", False):
        return "text-red-600"
    return ""
