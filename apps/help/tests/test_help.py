import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.urls import reverse

from apps.help.views import AREAS

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

SECTIONS = ["What it's for", "How we recommend setting it up", "How do I…", "Terms"]

HELP_URLS = [reverse("help_index")] + [
    reverse("help_area", args=[slug]) for slug in AREAS
]


def _text(body: str) -> str:
    main = body.split('<main id="main"', 1)[1].split("</main>", 1)[0]
    return re.sub(r"<[^>]+>", " ", main)


@pytest.mark.parametrize("url", HELP_URLS)
def test_anonymous_is_redirected_to_login(client: Client, url: str) -> None:
    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_unknown_area_is_not_found(signed_in: Client) -> None:
    assert signed_in.get("/help/nowhere/").status_code == 404


def test_help_is_the_last_nav_item_and_lives_in_the_more_sheet(
    signed_in: Client,
) -> None:
    response = signed_in.get(reverse("index"))

    assert response.context["nav_all"][-1]["label"] == "Help"
    assert response.context["nav_more"][-1]["url"] == reverse("help_index")


def test_help_is_marked_on_an_area_page(signed_in: Client) -> None:
    body = signed_in.get(reverse("help_area", args=["goals"])).content.decode()

    assert f'href="{reverse("help_index")}" aria-current="page"' in body


def test_index_starts_with_getting_started_and_links_every_area(
    signed_in: Client,
) -> None:
    text = _text(signed_in.get(reverse("help_index")).content.decode())
    body = signed_in.get(reverse("help_index")).content.decode()

    assert "Getting started" in text
    assert len(AREAS) == 10
    for slug in AREAS:
        assert f'href="{reverse("help_area", args=[slug])}"' in body


@pytest.mark.parametrize("slug", AREAS)
def test_area_page_has_the_four_sections_in_order(signed_in: Client, slug: str) -> None:
    body = signed_in.get(reverse("help_area", args=[slug])).content.decode()
    main = body.split('<main id="main"', 1)[1].split("</main>", 1)[0]
    headings = re.findall(r"<h2[^>]*>([^<]+)</h2>", main)

    assert headings == SECTIONS


@pytest.mark.parametrize("slug", AREAS)
def test_area_page_answers_what_happens_if(signed_in: Client, slug: str) -> None:
    text = _text(signed_in.get(reverse("help_area", args=[slug])).content.decode())

    assert "What happens if" in text or "What happens to" in text


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


@pytest.mark.parametrize("url", HELP_URLS)
def test_no_page_uses_an_avoided_term(signed_in: Client, url: str) -> None:
    text = _text(signed_in.get(url).content.decode())

    used = {
        term
        for term in _avoided_terms()
        # Whole words only, so "cap" doesn't catch a flexi-cap fund.
        if re.search(rf"(?<![\w-]){re.escape(term)}s?(?![\w-])", text, re.IGNORECASE)
    }
    assert used == set()
