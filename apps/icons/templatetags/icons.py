import re
from functools import cache
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

FALLBACK = "tag"
_CLASS_ATTR = re.compile(r'class="([^"]*)"')


@cache
def read_icon(directory: str, name: str) -> str | None:
    path = Path(directory) / f"{name}.svg"
    # Names come from user-editable data; never let one escape the directory.
    if path.parent != Path(directory) or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


@register.simple_tag
def icon(name: str, css_class: str = "") -> SafeString:
    directory = str(settings.LUCIDE_ICON_DIR)
    svg = read_icon(directory, name) or read_icon(directory, FALLBACK) or ""
    if css_class:
        extra = escape(css_class)
        svg = _CLASS_ATTR.sub(lambda m: f'class="{m.group(1)} {extra}"', svg, count=1)
    return mark_safe(svg)  # noqa: S308
