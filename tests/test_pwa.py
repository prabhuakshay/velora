import json
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_manifest_is_public_json(client: Client) -> None:
    response = client.get(reverse("manifest"))

    assert response["Content-Type"] == "application/manifest+json"
    manifest = json.loads(response.content)
    assert manifest["start_url"] == "/"
    assert {"192x192", "512x512"} <= {i["sizes"] for i in manifest["icons"]}


def test_service_worker_is_served_from_root(client: Client) -> None:
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/javascript"


def test_offline_page_is_public(client: Client) -> None:
    response = client.get(reverse("offline"))

    assert response.status_code == 200


def test_pages_link_the_manifest(client: Client) -> None:
    response = client.get(reverse("login"))

    assert reverse("manifest").encode() in response.content
