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

from apps.accounts.models import AccountKind
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party, Tag

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings

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
    "trade_price.js",
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
        name
        for name in named - {"htmx.min.js", "driver.js"}
        if not finders.find(f"js/{name}")
    ] == []


def test_home_loads_only_shared_scripts(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "js/app_shell.js" in body
    assert [name for name in PAGE_SCRIPTS if f"js/{name}" in body] == []


def test_budgets_page_loads_budget_sheet(signed_in: Client) -> None:
    body = signed_in.get(reverse("budget_list")).content.decode()

    tag = next(line for line in body.splitlines() if "js/budget_sheet.js" in line)
    assert 'hx-preserve="true"' in tag


QUICK_ADD_BUTTON = 'aria-label="Quick Add" data-dialog-open="quick-add"'


@pytest.fixture
def ai_on(settings: Settings) -> None:
    settings.OPENROUTER_API_KEY = "test-key"


def _shell_has_quick_add_button(client: Client, url: str) -> bool:
    body = client.get(url).content.decode()
    return QUICK_ADD_BUTTON in body and '<dialog id="quick-add"' in body


@pytest.mark.usefixtures("ai_on")
def test_the_quick_add_sent_message_waits_in_the_page(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    status = body[body.index('id="quick-add-status"') :]
    assert status.index("<template") < status.index("Quick Add sent")


@pytest.mark.usefixtures("ai_on")
def test_ordinary_pages_offer_the_quick_add_button(signed_in: Client) -> None:
    account = make_account("HDFC", AccountKind.ASSET)

    for url in [
        reverse("index"),
        reverse("transaction_list"),
        reverse("account_transactions", args=[account.kind, account.pk]),
    ]:
        assert _shell_has_quick_add_button(signed_in, url), url


def test_no_page_offers_the_quick_add_button_without_the_ai(
    signed_in: Client, settings: Settings
) -> None:
    settings.OPENROUTER_API_KEY = ""

    for name in ["index", "transaction_list", "draft_list"]:
        assert not _shell_has_quick_add_button(signed_in, reverse(name)), name


@pytest.mark.usefixtures("ai_on")
def test_drafts_and_form_pages_leave_out_the_quick_add_button(
    signed_in: Client,
) -> None:
    account = make_account("HDFC", AccountKind.ASSET)
    party = Party.objects.create(name="Toit")
    tag = Tag.objects.create(name="Food")
    at_account = [account.kind, account.pk]

    for url in [
        reverse("draft_list"),
        reverse("draft_create"),
        reverse("transaction_create"),
        reverse("schedule_create"),
        reverse("party_create"),
        reverse("party_edit", args=[party.pk]),
        reverse("party_merge", args=[party.pk]),
        reverse("party_delete", args=[party.pk]),
        reverse("tag_create"),
        reverse("tag_edit", args=[tag.pk]),
        reverse("account_create", args=[account.kind]),
        reverse("account_edit", args=at_account),
        reverse("account_reconcile", args=at_account),
        reverse("account_merge", args=at_account),
        reverse("account_delete", args=at_account),
        reverse("preferences"),
        reverse("password_change"),
    ]:
        response = signed_in.get(url)
        assert response.status_code == 200, url
        assert not _shell_has_quick_add_button(signed_in, url), url


@pytest.mark.usefixtures("ai_on")
def test_auth_pages_leave_out_the_quick_add_button(client: Client) -> None:
    for name in ["login", "password_reset"]:
        assert not _shell_has_quick_add_button(client, reverse(name)), name
