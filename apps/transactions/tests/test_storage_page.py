import re
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.transactions.models import Attachment, Transaction
from apps.transactions.tests.conftest import attach, recorded, transaction_url
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


def test_shows_size_and_count_by_file_type(signed_in: Client) -> None:
    rent = recorded("rent")
    attach(rent, "a.jpg", b"x" * 1024, "image/jpeg")
    attach(rent, "b.png", b"x" * 2048, "image/png")
    attach(rent, "c.pdf", b"x" * 4096, "application/pdf")
    attach(rent, "d.txt", b"x" * 512, "text/plain")

    text = storage_page(signed_in)

    assert "Images 2 3.0 KB" in text
    assert "PDF 1 4.0 KB" in text
    assert "Other 1 512 bytes" in text


def test_lists_largest_attachments_linking_to_their_transactions(
    signed_in: Client,
) -> None:
    rent = recorded("rent")
    lunch = recorded("lunch")
    attach(rent, "lease.pdf", b"x" * 3072)
    attach(lunch, "receipt.jpg", b"x" * 1024, "image/jpeg")
    for index in range(10):
        attach(lunch, f"tiny-{index}.txt", b"x", "text/plain")

    page = signed_in.get(reverse("storage")).content.decode()
    text = storage_page(signed_in)

    assert (
        "lease.pdf 3.0 KB 2026-03-01 rent receipt.jpg 1.0 KB 2026-03-01 lunch" in text
    )
    assert text.count("tiny-") == 8
    assert f'href="{transaction_url("transaction_edit", rent)}"' in page
    assert f'href="{transaction_url("transaction_edit", lunch)}"' in page


def test_lists_transactions_with_the_largest_attachment_total(
    signed_in: Client,
) -> None:
    rent = recorded("rent")
    lunch = recorded("lunch")
    attach(lunch, "a.pdf", b"x" * 2048)
    attach(rent, "b.pdf", b"x" * 1536)
    attach(rent, "c.pdf", b"x" * 1536)
    recorded("taxi")

    page = signed_in.get(reverse("storage")).content.decode()
    text = storage_page(signed_in)

    assert (
        "Largest Transactions 2026-03-01 rent 2 3.0 KB 2026-03-01 lunch 1 2.0 KB"
        in text
    )
    assert "taxi" not in text.split("Largest Transactions")[1]
    assert page.count(f'href="{transaction_url("transaction_edit", rent)}"') == 3


def test_shows_size_by_transaction_year(signed_in: Client) -> None:
    old = recorded("old")
    old.date = date(2024, 12, 31)
    old.save()
    attach(old, content=b"x" * 1024)
    attach(recorded("rent"), content=b"x" * 2048)
    attach(recorded("lunch"), content=b"x" * 2048)

    text = storage_page(signed_in)

    assert "Transaction year Attachments Size 2026 2 4.0 KB 2024 1 1.0 KB" in text


def months_before(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 - count
    return date(index // 12, index % 12 + 1, 1)


def attach_created_at(transaction: Transaction, moment: datetime, size: int) -> None:
    attachment = attach(transaction, content=b"x" * size)
    Attachment.objects.filter(pk=attachment.pk).update(created_at=moment)


def test_shows_attachments_added_in_each_of_the_last_12_months(
    signed_in: Client,
) -> None:
    this_month = timezone.localdate().replace(day=1)
    first_month = months_before(this_month, 11)
    window_start = timezone.make_aware(datetime.combine(first_month, time.min))
    rent = recorded("rent")
    attach_created_at(rent, window_start, 1024)
    attach_created_at(rent, window_start - timedelta(seconds=1), 4096)
    attach(rent, content=b"x" * 2048)
    attach(rent, content=b"x" * 2048)

    text = storage_page(signed_in)

    added = text.split("Added in the last 12 months")[1]
    assert added.startswith(f" Month Attachments Size {this_month:%b %Y} 2 4.0 KB ")
    assert f"{months_before(this_month, 1):%b %Y} 0 0 bytes" in added
    assert f"{first_month:%b %Y} 1 1.0 KB" in added
    assert f"{months_before(this_month, 12):%b %Y}" not in added


def test_with_no_attachments_every_breakdown_shows_an_empty_state(
    signed_in: Client,
) -> None:
    recorded("taxi")

    text = storage_page(signed_in)

    for heading in (
        "By file type",
        "Largest Attachments",
        "Largest Transactions",
        "By Transaction year",
    ):
        assert f"{heading} No Attachments yet." in text
    assert (
        "Added in the last 12 months No Attachments added in the last 12 months."
        in text
    )
