from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_index_redirects_anonymous_to_login(client: Client) -> None:
    response = client.get(reverse("index"))

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next=/"


def test_index_renders_for_signed_in_user(client: Client, user: User) -> None:
    client.force_login(user)

    response = client.get(reverse("index"))

    assert response.status_code == 200
    assert user.email.encode() in response.content
