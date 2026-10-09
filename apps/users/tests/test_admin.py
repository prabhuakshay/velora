import pytest
from django.test import Client
from django.urls import reverse

from apps.users.models import User
from conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(superuser: User) -> Client:
    client = Client()
    client.force_login(superuser)
    return client


@pytest.mark.parametrize(
    "url_name", ["admin:users_user_changelist", "admin:users_user_add"]
)
def test_admin_pages_load(admin_client: Client, url_name: str) -> None:
    assert admin_client.get(reverse(url_name)).status_code == 200


@pytest.mark.parametrize("url_name", ["change", "history"])
def test_admin_user_pages_load(
    admin_client: Client, superuser: User, url_name: str
) -> None:
    url = reverse(f"admin:users_user_{url_name}", args=[superuser.pk])

    assert admin_client.get(url).status_code == 200


def test_admin_add_user(admin_client: Client) -> None:
    response = admin_client.post(
        reverse("admin:users_user_add"),
        {
            "email": "New@Example.com",
            "full_name": "New Person",
            "usable_password": "true",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 302
    assert User.objects.filter(email="new@example.com").exists()


def test_admin_rejects_duplicate_email_in_other_case(
    admin_client: Client, superuser: User
) -> None:
    response = admin_client.post(
        reverse("admin:users_user_add"),
        {
            "email": superuser.email.upper(),
            "usable_password": "true",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 200
    assert User.objects.count() == 1


def hide(client: Client) -> None:
    client.post(reverse("privacy_mode_on"))


@pytest.mark.parametrize(
    "url_name",
    ["admin:index", "admin:users_user_changelist", "admin:users_user_change"],
)
def test_admin_redirects_to_unhide_page_in_privacy_mode(
    admin_client: Client, superuser: User, url_name: str
) -> None:
    args = [superuser.pk] if url_name.endswith("change") else []
    url = reverse(url_name, args=args)
    hide(admin_client)

    response = admin_client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('privacy_mode_off')}?next={url}"


def test_admin_loads_after_privacy_mode_is_turned_off(admin_client: Client) -> None:
    hide(admin_client)
    admin_client.post(reverse("privacy_mode_off"), {"password": PASSWORD})

    assert admin_client.get(reverse("admin:index")).status_code == 200
