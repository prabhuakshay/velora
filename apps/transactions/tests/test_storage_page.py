import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.transactions.models import Attachment
from apps.transactions.tests.conftest import attach, recorded
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def storage_page(client: Client) -> str:
    html = client.get(reverse("storage")).content.decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_storage_page_needs_sign_in(client: Client) -> None:
    url = reverse("storage")

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_shows_total_size_attachment_count_and_transactions_with_attachments(
    signed_in: Client,
) -> None:
    rent = recorded("rent")
    attach(rent, content=b"x" * 1024 * 1024)
    attach(rent, content=b"x" * 512 * 1024)
    attach(recorded("lunch"), content=b"x" * 512 * 1024)
    recorded("taxi")

    text = storage_page(signed_in)

    assert "Total size 2.0 MB" in text
    assert "Attachments 3" in text
    assert "Transactions with Attachments 2" in text


def test_shows_average_size_and_oldest_attachment_date(signed_in: Client) -> None:
    rent = recorded("rent")
    oldest = attach(rent, content=b"x" * 1024)
    attach(rent, content=b"x" * 2048)
    Attachment.objects.filter(pk=oldest.pk).update(
        created_at=datetime(2025, 7, 4, 12, tzinfo=UTC)
    )

    text = storage_page(signed_in)

    assert "Average size 1.5 KB" in text
    assert "Oldest Attachment 4 Jul 2025" in text


def test_with_no_attachments_shows_zeros_and_dashes(signed_in: Client) -> None:
    text = storage_page(signed_in)

    assert "Total size 0 bytes" in text
    assert "Attachments 0" in text
    assert "Transactions with Attachments 0" in text
    assert "Average size —" in text
    assert "Oldest Attachment —" in text


def test_figures_stay_visible_in_privacy_mode(signed_in: Client) -> None:
    attach(recorded("rent"), content=b"x" * 2048)
    turn_on(signed_in)

    text = storage_page(signed_in)

    assert "Total size 2.0 KB" in text
    assert "Attachments 1" in text


def test_preferences_links_to_the_storage_page(signed_in: Client) -> None:
    page = signed_in.get(reverse("preferences")).content.decode()

    assert f'href="{reverse("storage")}"' in page
