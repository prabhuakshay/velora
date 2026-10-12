from typing import TYPE_CHECKING

import pytest
from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def _render(user: User, *flash: Message) -> str:
    request = RequestFactory().get("/")
    request.user = user
    return render_to_string("app_base.html", {"messages": flash}, request=request)


@pytest.mark.parametrize(
    ("level", "role", "colour"),
    [
        (messages.ERROR, "alert", "bg-red-50"),
        (messages.WARNING, "alert", "bg-amber-50"),
        (messages.SUCCESS, "status", "bg-emerald-50"),
        (messages.INFO, "status", "bg-sky-50"),
    ],
)
def test_flash_message_styles_and_role_follow_level(
    user: User, level: int, role: str, colour: str
) -> None:
    html = _render(user, Message(level, "Hello"))
    tag = next(line for line in html.splitlines() if "Hello" in line)

    assert f'role="{role}"' in tag
    assert colour in tag


def test_skip_link_precedes_nav_and_targets_main(user: User) -> None:
    html = _render(user)

    before_nav = html.split("<aside")[0]
    assert 'href="#main"' in before_nav
    assert '<main id="main"' in html


def test_more_tab_is_active_on_a_page_that_lives_in_the_more_sheet(
    signed_in: Client,
) -> None:
    body = signed_in.get(reverse("tag_list")).content.decode()
    more_tab = body[: body.index("More\n")].rsplit("<button", 1)[1]

    assert "text-slate-900" in more_tab
    assert f'href="{reverse("party_list")}" aria-current="page"' in body


def test_phone_title_names_the_current_page(signed_in: Client) -> None:
    body = signed_in.get(reverse("schedule_list")).content.decode()

    assert '<p class="py-3 text-lg font-semibold tracking-tight">Schedules</p>' in body


@pytest.mark.parametrize("name", ["party_list", "tag_list"])
def test_classification_is_one_link_marked_on_parties_and_tags(
    signed_in: Client, name: str
) -> None:
    body = signed_in.get(reverse(name)).content.decode()

    assert f'href="{reverse("party_list")}" aria-current="page"' in body
    assert "Classification" in body
