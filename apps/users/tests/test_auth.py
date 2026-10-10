import re
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from conftest import PASSWORD

if TYPE_CHECKING:
    from django.core.mail import EmailMessage
    from django.test import Client
    from pytest_django import Settings

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_login_page_shows_client_ip(client: Client) -> None:
    response = client.get(reverse("login"), REMOTE_ADDR="203.0.113.7")

    assert b"203.0.113.7" in response.content


def test_login_page_shows_forwarded_client_ip(
    client: Client, settings: Settings
) -> None:
    settings.TRUSTED_PROXY_COUNT = 1

    response = client.get(
        reverse("login"), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.7"
    )

    assert b"203.0.113.7" in response.content
    assert b"10.0.0.1" not in response.content


def test_login_redirects_to_index(client: Client, user: User) -> None:
    response = client.post(
        reverse("login"), {"username": user.email, "password": PASSWORD}
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("index")


def test_login_rejects_wrong_password(client: Client, user: User) -> None:
    response = client.post(
        reverse("login"), {"username": user.email, "password": "wrong"}
    )

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_index_shows_logout_when_signed_in(client: Client, user: User) -> None:
    client.force_login(user)

    response = client.get(reverse("index"))

    assert reverse("logout").encode() in response.content


def test_sidebar_shows_profile_menu(client: Client, user: User) -> None:
    client.force_login(user)

    content = client.get(reverse("index")).content.decode()

    assert re.search(r"<summary[^>]*>\s*Profile\b", content)
    assert not re.search(r"<summary[^>]*>\s*Account\b", content)
    assert not re.search(r"<details[^>]*open>\s*<summary[^>]*>\s*Profile", content)


def test_profile_menu_opens_on_password_change_page(client: Client, user: User) -> None:
    client.force_login(user)

    content = client.get(reverse("password_change")).content.decode()

    assert re.search(r"<details[^>]*open>\s*<summary[^>]*>\s*Profile", content)


def test_logout_signs_out(client: Client, user: User) -> None:
    client.force_login(user)

    response = client.post(reverse("logout"))

    assert response["Location"] == reverse("login")
    assert "_auth_user_id" not in client.session


def test_password_reset_flow(
    client: Client, user: User, mailoutbox: list[EmailMessage]
) -> None:
    response = client.post(reverse("password_reset"), {"email": user.email})
    assert response["Location"] == reverse("password_reset_done")
    assert len(mailoutbox) == 1

    match = re.search(r"https?://[^/]+(/\S+)", str(mailoutbox[0].body))
    assert match
    # The emailed link redirects to a token-free URL before the form is shown.
    form_url = client.get(match.group(1))["Location"]
    new_password = "a-brand-new-passphrase"
    response = client.post(
        form_url, {"new_password1": new_password, "new_password2": new_password}
    )

    assert response["Location"] == reverse("password_reset_complete")
    user.refresh_from_db()
    assert user.check_password(new_password)


def test_password_reset_link_uses_site_url_not_request_host(
    client: Client, user: User, mailoutbox: list[EmailMessage], settings: Settings
) -> None:
    settings.SITE_URL = "https://velora.example.com"
    settings.ALLOWED_HOSTS = ["velora.example.com", "spoofed.example.net"]

    client.post(
        reverse("password_reset"),
        {"email": user.email},
        HTTP_HOST="spoofed.example.net",
    )

    body = str(mailoutbox[0].body)
    match = re.search(r"https?://\S+/reset/\S+", body)
    assert match
    assert match.group(0).startswith("https://velora.example.com/")
    assert "spoofed.example.net" not in body


def test_password_change_requires_login(client: Client) -> None:
    response = client.get(reverse("password_change"))

    assert response["Location"].startswith(reverse("login"))


def test_password_change_keeps_user_signed_in(client: Client, user: User) -> None:
    client.force_login(user)
    new_password = "a-brand-new-passphrase"

    response = client.post(
        reverse("password_change"),
        {
            "old_password": PASSWORD,
            "new_password1": new_password,
            "new_password2": new_password,
        },
    )

    assert response["Location"] == reverse("password_change_done")
    user.refresh_from_db()
    assert user.check_password(new_password)
    assert client.get(reverse("index")).status_code == 200


def test_password_help_text_is_linked_to_its_input(client: Client, user: User) -> None:
    client.force_login(user)

    response = client.get(reverse("password_change"))

    assert b'aria-describedby="id_new_password1_helptext"' in response.content
    assert b'id="id_new_password1_helptext"' in response.content
