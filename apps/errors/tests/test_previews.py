from typing import TYPE_CHECKING

import pytest
from django.test import Client
from django.urls import reverse

if TYPE_CHECKING:
    from pytest_django import Settings

    from apps.users.models import User

pytestmark = pytest.mark.django_db

PAGES = [
    ("400", 400, b"That request bounced"),
    ("403", 403, b"Access declined"),
    ("403-csrf", 403, b"signature expired"),
    ("404", 404, b"off the books"),
    ("429", 429, b"Too many requests"),
    ("429-locked", 429, b"Too many failed attempts"),
    ("500", 500, b"books don"),
]


@pytest.mark.parametrize(("name", "status", "text"), PAGES)
def test_preview_renders_page_with_status(
    client: Client, superuser: User, name: str, status: int, text: bytes
) -> None:
    client.force_login(superuser)

    response = client.get(reverse("errors:preview", args=[name]))

    assert response.status_code == status
    assert text in response.content


def test_previews_open_to_anyone_when_debug(client: Client, settings: Settings) -> None:
    settings.DEBUG = True

    assert client.get(reverse("errors:index")).status_code == 200


@pytest.mark.parametrize("url", [reverse("errors:index"), "/errors/404/"])
def test_previews_hidden_from_regular_users(
    client: Client, user: User, url: str
) -> None:
    client.force_login(user)

    response = client.get(url)

    assert response.status_code == 404
    assert b"off the books" in response.content


def test_index_lists_previews(client: Client, superuser: User) -> None:
    client.force_login(superuser)

    response = client.get(reverse("errors:index"))

    assert reverse("errors:preview", args=["500"]).encode() in response.content


def test_unknown_preview_is_404(client: Client, superuser: User) -> None:
    client.force_login(superuser)

    assert client.get(reverse("errors:preview", args=["418"])).status_code == 404


def test_missing_page_uses_custom_404(client: Client) -> None:
    response = client.get("/no-such-page/")

    assert response.status_code == 404
    assert b"/no-such-page/" in response.content


def test_csrf_failure_uses_custom_page(user: User) -> None:
    client = Client(enforce_csrf_checks=True)

    response = client.post(reverse("login"), {"username": user.email})

    assert response.status_code == 403
    assert b"signature expired" in response.content
