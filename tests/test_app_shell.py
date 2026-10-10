from typing import TYPE_CHECKING

import pytest
from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import RequestFactory

if TYPE_CHECKING:
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
