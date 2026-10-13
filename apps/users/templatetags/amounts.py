"""Show amounts in the signed-in user's Number Format."""

from typing import TYPE_CHECKING

from django import template
from django.utils.html import format_html
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


def _private(context: Context) -> bool:
    return getattr(context.get("user"), "privacy_mode", False)


@register.simple_tag(takes_context=True)
def amount(context: Context, value: Decimal) -> str:
    """The value with ₹, its sign and two decimals, grouped by Number Format.

    Under Privacy Mode, a fixed mask instead, so no real value reaches the HTML.
    """
    return _rupees(context, value, places=2)


@register.simple_tag(takes_context=True)
def price(context: Context, value: Decimal) -> str:
    """A Price as amount() shows it, but to four decimals as NAVs are quoted."""
    return _rupees(context, value, places=4)


def _rupees(context: Context, value: Decimal, *, places: int) -> str:
    if _private(context):
        return MASK
    number_format = getattr(context.get("user"), "number_format", NumberFormat.INDIAN)
    digits, fraction = f"{abs(value):.{places}f}".split(".")
    sign = "-" if value < 0 else ""
    return f"{sign}₹{_group(digits, number_format)}.{fraction}"


UNITS_MASK: SafeString = mark_safe(
    '<span role="img" aria-label="Units hidden">••••</span>'
)


@register.simple_tag(takes_context=True)
def units(context: Context, value: Decimal) -> str:
    """Units of an Instrument, grouped by Number Format, without trailing zeros.

    Masked under Privacy Mode, as units times a public Price give the value away.
    """
    if _private(context):
        return UNITS_MASK
    number_format = getattr(context.get("user"), "number_format", NumberFormat.INDIAN)
    digits, _, fraction = f"{abs(value).normalize():f}".partition(".")
    sign = "-" if value < 0 else ""
    grouped = _group(digits, number_format)
    return f"{sign}{grouped}.{fraction}" if fraction else f"{sign}{grouped}"


@register.simple_tag(takes_context=True)
def amount_color(context: Context, value: Decimal, *, owes: bool = False) -> str:
    """The class that shows a negative amount in red.

    Nothing for what is owed, where below zero is in credit, and nothing under
    Privacy Mode, where red would give away the sign.
    """
    if owes or _private(context):
        return ""
    return "text-red-600" if value < 0 else ""


@register.simple_tag(takes_context=True)
def balance(context: Context, value: Decimal, *, owes: bool = False) -> str:
    """The Balance as amount() shows it; one owed below zero reads as in credit."""
    if owes and value < 0 and not _private(context):
        return f"{amount(context, -value)} in credit"
    return amount(context, value)


@register.simple_tag(takes_context=True)
def signed_amount(context: Context, value: Decimal, good: str = "up") -> str:
    """The change with an explicit sign, green when it moves the good way.

    good is "up", "down", or "none" for a Transfer, shown muted and unsigned.
    Under Privacy Mode only the mask, as the sign or colour would give the
    value away.
    """
    if _private(context):
        return MASK
    text = amount(context, value)
    if good == "none":
        return format_html('<span class="text-slate-500">{}</span>', text)
    if value > 0:
        text = f"+{text}"
    if value and (value > 0) == (good == "up"):
        return format_html('<span class="text-emerald-600">{}</span>', text)
    return format_html("<span>{}</span>", text)
