import re
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.help.tests.conftest import avoided_terms_in
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


@pytest.mark.parametrize("url", HELP_URLS)
def test_no_page_uses_an_avoided_term(signed_in: Client, url: str) -> None:
    text = _text(signed_in.get(url).content.decode())

    assert avoided_terms_in(text) == set()
