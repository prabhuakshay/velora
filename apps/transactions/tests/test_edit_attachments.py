from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse

from apps.transactions.models import Attachment, Transaction
from apps.transactions.tests.conftest import (
    R2_ENDPOINT,
    attach,
    form_data,
    recorded,
    stored_names,
    transaction_url,
    upload,
)
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def attach_row(transaction: Transaction, name: str, content_type: str) -> Attachment:
    """An Attachment row only, for storages a test must not write to (R2)."""
    return Attachment.objects.create(
        transaction=transaction,
        file="attachments/0123456789abcdef",
        original_name=name,
        content_type=content_type,
        size=1,
    )


def test_edit_adds_new_files_to_existing_attachments(signed_in: Client) -> None:
    transaction = recorded()
    kept = attach(transaction, "bill.pdf", b"%PDF bill", "application/pdf")
    split = transaction.splits.get()

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        form_data(
            split.from_account,
            split.to_account,
            split_id=split.pk,
            attachments=upload("warranty.png", b"\x89PNG card"),
        ),
    )

    assert response.status_code == 302
    names = [a.original_name for a in transaction.attachments.all()]
    assert names == ["bill.pdf", "warranty.png"]
    assert len(stored_names()) == 2
    assert kept.file.name in stored_names()


@pytest.mark.usefixtures("second_save_fails")
def test_failure_mid_save_on_edit_leaves_no_new_files(signed_in: Client) -> None:
    transaction = recorded()
    split = transaction.splits.get()

    with pytest.raises(OSError, match="storage unavailable"):
        signed_in.post(
            transaction_url("transaction_edit", transaction),
            form_data(
                split.from_account,
                split.to_account,
                "999",
                split_id=split.pk,
                attachments=[
                    upload("one.pdf", b"%PDF one"),
                    upload("two.pdf", b"%PDF two"),
                ],
            ),
        )

    assert not transaction.attachments.exists()
    assert transaction.splits.get().amount == Decimal(100)
    assert stored_names() == []


def open_url(attachment: Attachment) -> str:
    return reverse("attachment_open", kwargs={"pk": attachment.pk})


def test_edit_page_lists_attachments_with_preview_or_icon_and_size(
    signed_in: Client,
) -> None:
    transaction = recorded()
    photo = attach(transaction, "receipt.jpg", b"\xff\xd8" * 1024, "image/jpeg")
    sheet = attach(transaction, "quote.xlsx", b"PK" * 786_432, "application/zip")

    page = signed_in.get(transaction_url("transaction_edit", transaction)).content
    body = page.decode()

    assert f'<img src="{open_url(photo)}"' in body
    assert f'<img src="{open_url(sheet)}"' not in body
    assert f'href="{open_url(sheet)}"' in body
    assert "receipt.jpg" in body
    assert "quote.xlsx" in body
    assert "2.0\xa0KB" in body
    assert "1.5\xa0MB" in body


def opened_with(client: Client, attachment: Attachment) -> dict[str, list[str]]:
    response = client.get(open_url(attachment))
    assert response.status_code == 302
    location = urlsplit(response["Location"])
    assert f"{location.scheme}://{location.netloc}" == R2_ENDPOINT
    assert location.path == f"/velora-test/{attachment.file.name}"
    query = parse_qs(location.query)
    assert query.pop("X-Amz-Expires") == ["300"]
    assert "X-Amz-Signature" in query
    return {
        name: values for name, values in query.items() if name.startswith("response-")
    }


@pytest.mark.usefixtures("r2_storage")
@pytest.mark.parametrize(
    ("name", "content_type"),
    [("receipt.jpg", "image/jpeg"), ("invoice.pdf", "application/pdf")],
)
def test_opening_an_image_or_pdf_shows_it_inline(
    signed_in: Client, name: str, content_type: str
) -> None:
    attachment = attach_row(recorded(), name, content_type)

    assert opened_with(signed_in, attachment) == {
        "response-content-disposition": [f'inline; filename="{name}"'],
        "response-content-type": [content_type],
    }


@pytest.mark.usefixtures("r2_storage")
def test_opening_another_type_downloads_it_under_its_original_name(
    signed_in: Client,
) -> None:
    attachment = attach_row(recorded(), "Quote 2026.xlsx", "application/zip")

    assert opened_with(signed_in, attachment) == {
        "response-content-disposition": ['attachment; filename="Quote 2026.xlsx"'],
        "response-content-type": ["application/zip"],
    }


def test_opening_needs_sign_in(client: Client) -> None:
    attachment = attach(recorded(), "receipt.jpg", b"content", "image/jpeg")
    url = open_url(attachment)

    response = client.get(url)

    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_opening_is_blocked_in_privacy_mode(signed_in: Client) -> None:
    attachment = attach(recorded(), "receipt.jpg", b"content", "image/jpeg")
    url = open_url(attachment)
    turn_on(signed_in)

    response = signed_in.get(url)

    assert response["Location"] == privacy_mode_off_url(url)
