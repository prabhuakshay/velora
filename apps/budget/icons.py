"""Lucide icons: the template tag that inlines them, search, and the picker's set."""

import json
import re
from functools import cache
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

register = template.Library()

FALLBACK = "tag"
MAX_RESULTS = 40
_CLASS_ATTR = re.compile(r'class="([^"]*)"')
_LEADING_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)

CURATED_ICONS = (
    "tag",
    "wallet",
    "house",
    "banknote",
    "credit-card",
    "piggy-bank",
    "coins",
    "receipt",
    "shopping-cart",
    "shopping-bag",
    "shopping-basket",
    "utensils",
    "coffee",
    "pizza",
    "wine",
    "beer",
    "car",
    "bus",
    "train-front",
    "plane",
    "fuel",
    "bike",
    "zap",
    "droplet",
    "flame",
    "wifi",
    "smartphone",
    "laptop",
    "tv",
    "gamepad-2",
    "film",
    "music",
    "book-open",
    "graduation-cap",
    "heart-pulse",
    "pill",
    "stethoscope",
    "dumbbell",
    "shirt",
    "scissors",
    "baby",
    "paw-print",
    "gift",
    "cake",
    "party-popper",
    "briefcase",
    "building-2",
    "landmark",
    "hammer",
    "wrench",
    "sofa",
    "trees",
    "umbrella",
    "shield-check",
    "trending-up",
    "percent",
    "hand-coins",
    "circle-dollar-sign",
    "calendar",
)


@cache
def _names(directory: str) -> frozenset[str]:
    return frozenset(path.stem for path in Path(directory).glob("*.svg"))


@cache
def _index(directory: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    root = Path(directory)
    tags_file = root / "tags.json"
    tags: dict[str, list[str]] = (
        json.loads(tags_file.read_text(encoding="utf-8")) if tags_file.is_file() else {}
    )
    return tuple(
        (path.stem, tuple(tags.get(path.stem, ())))
        for path in sorted(root.glob("*.svg"))
    )


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


def search_icons(directory: str, query: str, limit: int = MAX_RESULTS) -> list[str]:
    """Return icon names whose name or tags contain the query."""
    needle = query.strip().lower()
    if not needle:
        return []
    matches = [
        name
        for name, keywords in _index(directory)
        if needle in name or any(needle in keyword.lower() for keyword in keywords)
    ]
    return matches[:limit]


@register.simple_tag
def icon(name: str, css_class: str = "") -> SafeString:
    """Inline an icon's SVG, falling back to the tag, with extra classes."""
    directory = str(settings.LUCIDE_ICON_DIR)
    svg = read_icon(directory, name) or read_icon(directory, FALLBACK) or ""
    if css_class:
        extra = escape(css_class)
        svg = _CLASS_ATTR.sub(lambda m: f'class="{m.group(1)} {extra}"', svg, count=1)
    return mark_safe(svg)  # noqa: S308
