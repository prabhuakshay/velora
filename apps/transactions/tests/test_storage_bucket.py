import re
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.transactions import r2_bucket
from apps.transactions.tests.conftest import attach, recorded

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def bucket_section(client: Client) -> str:
    html = client.get(reverse("storage_bucket")).content.decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def listing_returns(
    monkeypatch: pytest.MonkeyPatch, objects: list[tuple[str, int]]
) -> None:
    monkeypatch.setattr(r2_bucket, "list_objects", lambda: objects)


def test_shows_object_count_and_total_size_of_the_whole_bucket(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing_returns(
        monkeypatch,
        [
            ("attachments/a", 1024 * 1024),
            ("attachments/b", 512 * 1024),
            ("backups/db.sql", 512 * 1024),
        ],
    )

    text = bucket_section(signed_in)

    assert "Objects 3" in text
    assert "Total size 2.0 MB" in text


def test_shows_untracked_objects_including_keys_outside_the_attachment_prefix(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracked = attach(recorded("rent"))
    listing_returns(
        monkeypatch,
        [
            (str(tracked.file.name), 4096),
            ("attachments/stray", 1024),
            ("backups/db.sql", 2048),
        ],
    )

    text = bucket_section(signed_in)

    assert "Untracked objects 2" in text
    assert "Untracked size 3.0 KB" in text
    assert "Missing objects 0" in text


def test_shows_attachments_whose_object_is_missing(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    rent = recorded("rent")
    kept = attach(rent)
    attach(rent)
    attach(recorded("lunch"))
    listing_returns(monkeypatch, [(str(kept.file.name), 1024)])

    text = bucket_section(signed_in)

    assert "Missing objects 2" in text
    assert "Untracked objects 0" in text


def test_a_listing_error_shows_a_note_instead_of_the_figures(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable() -> list[tuple[str, int]]:
        raise ConnectionError

    monkeypatch.setattr(r2_bucket, "list_objects", unreachable)

    response = signed_in.get(reverse("storage_bucket"))
    text = bucket_section(signed_in)

    assert response.status_code == 200
    assert "Couldn't reach R2" in text
    assert "Objects" not in text


def test_bucket_section_needs_sign_in(client: Client) -> None:
    url = reverse("storage_bucket")

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_storage_page_loads_the_bucket_section_after_rendering(
    signed_in: Client,
) -> None:
    page = signed_in.get(reverse("storage")).content.decode()

    assert f'hx-get="{reverse("storage_bucket")}"' in page
    assert 'hx-trigger="load"' in page
