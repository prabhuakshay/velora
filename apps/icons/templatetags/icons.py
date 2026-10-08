"""Template tag that inlines Lucide icons as SVG."""

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


_LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


@cache
def _names(directory: str) -> frozenset[str]:
    return frozenset(path.stem for path in Path(directory).glob("*.svg"))


@cache
def load_svg(directory: str, name: str) -> str:
    """Read an icon's SVG without its leading licence comment."""
    svg = (Path(directory) / f"{name}.svg").read_text(encoding="utf-8")
    return _LEADING_COMMENT.sub("", svg, count=1)


def read_icon(directory: str, name: str) -> str | None:
    """Return the named icon's SVG, or None if no such icon exists."""
    # Checking the directory listing first keeps the cache bounded to real icons,
    # and stops names from user-editable data escaping the directory.
    if name not in _names(directory):
        return None
    return load_svg(directory, name)


@register.simple_tag
def icon(name: str, css_class: str = "") -> SafeString:
    """Inline an icon's SVG, falling back to the tag, with extra classes."""
    directory = str(settings.LUCIDE_ICON_DIR)
    svg = read_icon(directory, name) or read_icon(directory, FALLBACK) or ""
    if css_class:
        extra = escape(css_class)
        svg = _CLASS_ATTR.sub(lambda m: f'class="{m.group(1)} {extra}"', svg, count=1)
    return mark_safe(svg)  # noqa: S308
