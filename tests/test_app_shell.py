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
    assert f'href="{reverse("tag_list")}" aria-current="page"' in body


def test_phone_title_names_the_current_page(signed_in: Client) -> None:
    body = signed_in.get(reverse("account_list", args=["liability"])).content.decode()

    assert '<p class="py-3 text-lg font-semibold tracking-tight">Liability</p>' in body


def _accounts_section(body: str) -> str:
    return next(
        line for line in body.splitlines() if 'data-nav-section="accounts"' in line
    )


def test_sidebar_sections_start_collapsed(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert not _accounts_section(body).endswith(" open>")


def test_sidebar_section_stays_expanded_from_cookie(signed_in: Client) -> None:
    signed_in.cookies["nav_expanded"] = "accounts.classification"
    body = signed_in.get(reverse("index")).content.decode()

    assert _accounts_section(body).endswith(" open>")


def test_section_expands_when_it_holds_the_current_page(signed_in: Client) -> None:
    body = signed_in.get(reverse("account_list", args=["asset"])).content.decode()

    assert _accounts_section(body).endswith(" open>")
