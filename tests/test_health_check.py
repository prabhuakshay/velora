from typing import TYPE_CHECKING

import pytest
from django.test import override_settings

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


@override_settings(ALLOWED_HOSTS=["example.com"], SECURE_SSL_REDIRECT=True)
def test_health_check_skips_host_and_https_checks(client: Client) -> None:
    response = client.get("/healthz/", HTTP_HOST="127.0.0.1")

    assert response.status_code == 200
    assert response.content == b"ok"
