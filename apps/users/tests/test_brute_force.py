from typing import TYPE_CHECKING

import pytest
from axes.models import AccessAttempt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.urls import reverse

from conftest import PASSWORD

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse
    from pytest_django import Settings

    from apps.users.models import User

pytestmark = pytest.mark.django_db

NEW_PASSWORD = "a-brand-new-passphrase"


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
    assert b"Account locked" in response.content
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
    assert "429.html" in [t.name for t in response.templates]


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


def test_invalid_rate_is_rejected(client: Client, settings: Settings) -> None:
    settings.LOGIN_RATE_LIMIT = "5/w"

    with pytest.raises(ImproperlyConfigured):
        client.post(reverse("login"), {"username": "a@example.com", "password": "x"})


def change_password(
    client: Client,
    old_password: str,
    new_password: str = NEW_PASSWORD,
    ip: str = "203.0.113.7",
) -> _MonkeyPatchedWSGIResponse:
    return client.post(
        reverse("password_change"),
        {
            "old_password": old_password,
            "new_password1": new_password,
            "new_password2": new_password,
        },
        REMOTE_ADDR=ip,
    )


def test_wrong_old_password_is_rejected(signed_in: Client, user: User) -> None:
    response = change_password(signed_in, "wrong")

    assert response.status_code == 200
    assert b"entered incorrectly" in response.content
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_wrong_old_password_is_recorded_by_axes(signed_in: Client, user: User) -> None:
    change_password(signed_in, "wrong")

    attempt = AccessAttempt.objects.get()
    assert attempt.username == user.email
    assert attempt.ip_address == "203.0.113.7"


def test_wrong_old_passwords_lock_out_password_change_and_login(
    signed_in: Client, user: User
) -> None:
    for _ in range(settings.AXES_FAILURE_LIMIT):
        change_password(signed_in, "wrong")

    change_response = change_password(signed_in, PASSWORD)
    login_response = Client().post(
        reverse("login"),
        {"username": user.email, "password": PASSWORD},
        REMOTE_ADDR="203.0.113.7",
    )

    assert change_response.status_code == 429
    assert b"Account locked" in change_response.content
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert login_response.status_code == 429


def test_login_lockout_blocks_password_change(client: Client, user: User) -> None:
    for _ in range(settings.AXES_FAILURE_LIMIT):
        fail_login(client, user.email)
    client.force_login(user)

    response = change_password(client, PASSWORD)

    assert response.status_code == 429
    assert b"Account locked" in response.content
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_password_change_clears_earlier_failures(signed_in: Client, user: User) -> None:
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        change_password(signed_in, "wrong")
    assert change_password(signed_in, PASSWORD).status_code == 302
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        fail_login(Client(), user.email)

    response = Client().post(
        reverse("login"),
        {"username": user.email, "password": NEW_PASSWORD},
        REMOTE_ADDR="203.0.113.7",
    )

    assert response.status_code == 302


def test_password_change_posts_are_rate_limited_per_ip(
    signed_in: Client, settings: Settings
) -> None:
    # A per-minute window could reset mid-test.
    settings.LOGIN_RATE_LIMIT = "3/d"
    for _ in range(3):
        change_password(signed_in, "wrong", ip="198.51.100.1")

    response = change_password(signed_in, "wrong", ip="198.51.100.1")

    assert response.status_code == 429
    assert "429.html" in [t.name for t in response.templates]
