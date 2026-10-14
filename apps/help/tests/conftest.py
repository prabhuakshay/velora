import re
from pathlib import Path

from django.conf import settings

# Labels Velora itself shows, which Help quotes so the user can find them.
UI_LABELS = {"total", "confirm", "delete", "dismiss", "note", "overdue", "principal"}


def _avoided_terms() -> list[str]:
    """Avoided terms, less those the glossary's own definitions use as plain words."""
    glossary = Path(settings.BASE_DIR, "GLOSSARY.md").read_text()
    definitions = re.sub(r"^_Avoid_: .+$", "", glossary, flags=re.MULTILINE)
    terms = []
    for line in re.findall(r"^_Avoid_: (.+)$", glossary, re.MULTILINE):
        # "Split (that is part of a Transaction)" avoids a sense, not a word.
        terms += [t.strip() for t in line.split(",") if "(" not in t]
    return [
        term
        for term in terms
        if term.lower() not in UI_LABELS
        and not re.search(rf"\b{re.escape(term)}\b", definitions, re.IGNORECASE)
    ]


def avoided_terms_in(text: str) -> set[str]:
    return {
        term
        for term in _avoided_terms()
        # Whole words only, so "cap" doesn't catch a flexi-cap fund.
        if re.search(rf"(?<![\w-]){re.escape(term)}s?(?![\w-])", text, re.IGNORECASE)
    }
