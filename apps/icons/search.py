import json
from functools import cache
from pathlib import Path

MAX_RESULTS = 40


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


def search_icons(directory: str, query: str, limit: int = MAX_RESULTS) -> list[str]:
    needle = query.strip().lower()
    if not needle:
        return []
    matches = [
        name
        for name, keywords in _index(directory)
        if needle in name or any(needle in keyword.lower() for keyword in keywords)
    ]
    return matches[:limit]
