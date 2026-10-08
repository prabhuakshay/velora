from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_signed_in_page_is_not_stored(client: Client, user: User) -> None:
    client.force_login(user)

    response = client.get(reverse("index"))

    assert "no-store" in response["Cache-Control"]


def test_login_page_is_not_stored(client: Client) -> None:
    response = client.get(reverse("login"))

    assert "no-store" in response["Cache-Control"]


def test_failed_login_drops_post_from_history(client: Client, user: User) -> None:
    response = client.post(
        reverse("login"), {"username": user.email, "password": "wrong"}
    )

    assert b"history.replaceState" in response.content


def test_login_page_leaves_history_alone(client: Client) -> None:
    response = client.get(reverse("login"))

    assert b"history.replaceState" not in response.content
