from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from django.template import engines
from django.test import override_settings

from apps.icons.templatetags import icons

if TYPE_CHECKING:
    import pytest


def render(template: str) -> str:
    return engines["django"].from_string(template).render({})


def test_renders_known_icon_as_inline_svg() -> None:
    html = render('{% icon "wallet" %}')

    assert "<svg" in html
    assert "lucide-wallet" in html
    assert 'stroke="currentColor"' in html


def test_adds_extra_classes() -> None:
    html = render('{% icon "wallet" "size-5 text-red-500" %}')

    assert 'class="lucide lucide-wallet size-5 text-red-500"' in html


def test_unknown_icon_falls_back_to_tag() -> None:
    html = render('{% icon "does-not-exist" %}')

    assert "lucide-tag" in html


def test_path_traversal_name_falls_back_to_tag() -> None:
    html = render('{% icon "../tags" %}')

    assert "lucide-tag" in html


def test_repeated_renders_do_not_reread_file(monkeypatch: pytest.MonkeyPatch) -> None:
    icons.load_svg.cache_clear()
    reads: list[Path] = []
    original = Path.read_text

    def spy(self: Path, *args: object, **kwargs: object) -> str:
        reads.append(self)
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", spy)

    render('{% icon "house" %}')
    render('{% icon "house" "size-4" %}')

    assert len([p for p in reads if p.name == "house.svg"]) == 1


def test_icon_directory_comes_from_setting(tmp_path: Path) -> None:
    (tmp_path / "tag.svg").write_text('<svg class="lucide lucide-tag"></svg>')
    icons.load_svg.cache_clear()

    with override_settings(LUCIDE_ICON_DIR=tmp_path):
        html = render('{% icon "wallet" %}')

    assert "lucide-tag" in html
    icons.load_svg.cache_clear()


def test_license_comment_is_stripped() -> None:
    assert "@license" not in render('{% icon "wallet" %}')


def test_unknown_names_are_not_cached() -> None:
    icons.load_svg.cache_clear()

    for i in range(5):
        render(f'{{% icon "nope-{i}" %}}')

    assert icons.load_svg.cache_info().currsize <= 1
