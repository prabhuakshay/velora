import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.contrib.staticfiles import finders
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


PAGE_SCRIPTS = [
    "attachment_limit.js",
    "transaction_list.js",
    "transaction_form.js",
    "list_filter.js",
    "budget_sheet.js",
]


def test_no_page_loads_alpine(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "alpine" not in body.lower()


def test_every_script_a_template_names_exists() -> None:
    templates = Path(settings.BASE_DIR, "templates").rglob("*.html")
    named = {
        name
        for template in templates
        for name in re.findall(r"{% static 'js/([^']+\.js)' %}", template.read_text())
    }

    assert set(PAGE_SCRIPTS) <= named
    # Vendored by npm, which CI doesn't run.
    assert [
        name for name in named - {"htmx.min.js"} if not finders.find(f"js/{name}")
    ] == []


def test_home_loads_only_shared_scripts(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "js/app_shell.js" in body
    assert [name for name in PAGE_SCRIPTS if f"js/{name}" in body] == []


def test_budgets_page_loads_budget_sheet(signed_in: Client) -> None:
    body = signed_in.get(reverse("budget_list")).content.decode()

    tag = next(line for line in body.splitlines() if "js/budget_sheet.js" in line)
    assert 'hx-preserve="true"' in tag
