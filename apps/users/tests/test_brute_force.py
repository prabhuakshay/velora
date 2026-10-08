from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.urls import reverse

from conftest import PASSWORD

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def fail_login(client: Client, username: str, ip: str = "203.0.113.7") -> None:
    client.post(
        reverse("login"), {"username": username, "password": "wrong"}, REMOTE_ADDR=ip
    )


def test_repeated_failures_lock_out_username_and_ip(client: Client, user: User) -> None:
    for _ in range(settings.AXES_FAILURE_LIMIT):
        fail_login(client, user.email)

    response = client.post(
        reverse("login"),
        {"username": user.email, "password": PASSWORD},
        REMOTE_ADDR="203.0.113.7",
    )

    assert response.status_code == 429
    assert b"Too many failed attempts" in response.content
    assert "_auth_user_id" not in client.session


def test_lockout_does_not_block_user_from_other_ip(client: Client, user: User) -> None:
    for _ in range(settings.AXES_FAILURE_LIMIT):
        fail_login(client, user.email)

    response = client.post(
        reverse("login"),
        {"username": user.email, "password": PASSWORD},
        REMOTE_ADDR="198.51.100.1",
    )

    assert response.status_code == 302


def test_login_posts_are_rate_limited_per_ip(
    client: Client, settings: Settings
) -> None:
    # A per-minute window could reset mid-test.
    settings.LOGIN_RATE_LIMIT = "3/d"
    for i in range(3):
        fail_login(client, f"user{i}@example.com")

    response = client.post(
        reverse("login"),
        {"username": "other@example.com", "password": "wrong"},
        REMOTE_ADDR="203.0.113.7",
    )

    assert response.status_code == 429
    assert b"Too many requests" in response.content


def test_password_reset_posts_are_rate_limited_per_ip(client: Client) -> None:
    for _ in range(5):
        client.post(reverse("password_reset"), {"email": "someone@example.com"})

    response = client.post(reverse("password_reset"), {"email": "someone@example.com"})

    assert response.status_code == 429


def test_lockout_ignores_email_case(client: Client, user: User) -> None:
    for _ in range(settings.AXES_FAILURE_LIMIT):
        fail_login(client, user.email.upper())

    response = client.post(
        reverse("login"),
        {"username": user.email, "password": PASSWORD},
        REMOTE_ADDR="203.0.113.7",
    )

    assert response.status_code == 429


def test_rate_limit_uses_forwarded_client_ip(
    client: Client, settings: Settings
) -> None:
    settings.TRUSTED_PROXY_COUNT = 1
    for _ in range(5):
        client.post(
            reverse("password_reset"),
            {"email": "someone@example.com"},
            HTTP_X_FORWARDED_FOR="203.0.113.7",
        )

    response = client.post(
        reverse("password_reset"),
        {"email": "someone@example.com"},
        HTTP_X_FORWARDED_FOR="198.51.100.1",
    )

    assert response.status_code == 302
