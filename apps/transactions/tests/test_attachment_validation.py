import io
import zipfile
from typing import TYPE_CHECKING

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import (
    form_data,
    stored_names,
    transaction_url,
)

if TYPE_CHECKING:
    from django.test import Client
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

pytestmark = pytest.mark.django_db


def upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


def create_with(client: Client, *files: SimpleUploadedFile) -> Response:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    return client.post(
        reverse("transaction_create"),
        form_data(bank, groceries, attachments=list(files)),
    )


def zipped(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ODT = "application/vnd.oasis.opendocument.text"
ODS = "application/vnd.oasis.opendocument.spreadsheet"


@pytest.mark.parametrize(
    ("name", "content", "content_type"),
    [
        ("photo.jpg", b"\xff\xd8\xff\xe0 jfif", "image/jpeg"),
        ("photo.JPEG", b"\xff\xd8\xff\xe1 exif", "image/jpeg"),
        ("scan.png", b"\x89PNG\r\n\x1a\n", "image/png"),
        ("snap.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        ("iphone.heic", b"\x00\x00\x00\x18ftypheic\x00\x00", "image/heic"),
        ("anim.gif", b"GIF89a\x01\x00", "image/gif"),
        ("invoice.pdf", b"%PDF-1.7\n", "application/pdf"),
        ("notes.txt", "Paid ₹500 in cash".encode(), "text/plain"),
        ("notes.md", b"# Warranty\n\nTwo years.", "text/markdown"),
        ("export.csv", b"date,amount\n2026-03-01,100\n", "text/csv"),
        ("quote.docx", zipped({"word/document.xml": b"<w/>"}), DOCX),
        ("budget.xlsx", zipped({"xl/workbook.xml": b"<x/>"}), XLSX),
        ("lease.odt", zipped({"mimetype": ODT.encode()}), ODT),
        ("sheet.ods", zipped({"mimetype": ODS.encode()}), ODS),
    ],
)
def test_file_of_each_allowed_type_is_stored_with_its_content_type(
    signed_in: Client, name: str, content: bytes, content_type: str
) -> None:
    response = create_with(signed_in, upload(name, content))

    assert response["Location"] == reverse("transaction_list")
    attachment = Transaction.objects.get().attachments.get()
    assert (attachment.original_name, attachment.content_type) == (name, content_type)
    assert attachment.file.read() == content
    assert stored_names() == [attachment.file.name]


def assert_rejected(response: Response, message: str) -> None:
    assert response.status_code == 200
    assert message in response.content.decode()
    assert not Transaction.objects.exists()
    assert stored_names() == []


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("drawing.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
        ("page.html", b"<!doctype html><html></html>"),
        ("setup.exe", b"MZ\x90\x00"),
        ("noextension", b"plain words"),
    ],
)
def test_disallowed_type_is_rejected(
    signed_in: Client, name: str, content: bytes
) -> None:
    response = create_with(signed_in, upload(name, content))

    assert_rejected(response, f"{name} isn&#x27;t a file type you can attach.")


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("receipt.pdf", b"MZ\x90\x00 not a pdf"),
        ("photo.jpg", b"\x89PNG\r\n\x1a\n a png"),
        ("notes.txt", b"\x00\x01\x02 binary"),
        ("export.csv", b"\xff\xd8\xff\xe0 a jpeg"),
        ("notes.md", b"<!DOCTYPE html><html><script></script></html>"),
        ("data.csv", b'  <svg xmlns="http://www.w3.org/2000/svg"></svg>'),
        ("quote.docx", b"PK\x03\x04 not really a zip"),
    ],
)
def test_file_whose_content_does_not_match_its_extension_is_rejected(
    signed_in: Client, name: str, content: bytes
) -> None:
    response = create_with(signed_in, upload(name, content))

    assert_rejected(response, f"{name} doesn&#x27;t contain what its file type says.")


MB = 1024 * 1024


def test_file_over_20_mb_is_rejected_naming_the_limit(signed_in: Client) -> None:
    big = upload("scan.pdf", b"%PDF" + b"0" * (20 * MB - 3))

    response = create_with(signed_in, big)

    assert_rejected(response, "scan.pdf is over 20 MB, the most an Attachment can be.")


def test_file_of_exactly_20_mb_is_accepted(signed_in: Client) -> None:
    response = create_with(
        signed_in, upload("scan.pdf", b"%PDF" + b"0" * (20 * MB - 4))
    )

    assert response["Location"] == reverse("transaction_list")
    assert len(stored_names()) == 1


def pdfs(count: int) -> list[SimpleUploadedFile]:
    return [upload(f"page{number}.pdf", b"%PDF page") for number in range(count)]


TOO_MANY = "A Transaction can have at most 10 Attachments."


def test_ten_files_on_a_new_transaction_are_accepted(signed_in: Client) -> None:
    create_with(signed_in, *pdfs(10))

    assert Transaction.objects.get().attachments.count() == 10


def test_eleven_files_on_a_new_transaction_are_rejected(signed_in: Client) -> None:
    response = create_with(signed_in, *pdfs(11))

    assert_rejected(response, TOO_MANY)


def edit_with(
    client: Client, transaction: Transaction, *files: SimpleUploadedFile
) -> Response:
    split = transaction.splits.get()
    return client.post(
        transaction_url("transaction_edit", transaction),
        form_data(
            split.from_account,
            split.to_account,
            split_id=split.pk,
            description="Changed",
            attachments=list(files),
        ),
    )


def test_edit_counts_existing_attachments_towards_the_limit(
    signed_in: Client,
) -> None:
    create_with(signed_in, *pdfs(9))
    transaction = Transaction.objects.get()
    existing = stored_names()

    response = edit_with(signed_in, transaction, *pdfs(2))

    assert TOO_MANY in response.content.decode()
    transaction.refresh_from_db()
    assert transaction.description == ""
    assert transaction.attachments.count() == 9
    assert stored_names() == existing


def test_edit_may_fill_up_to_the_limit(signed_in: Client) -> None:
    create_with(signed_in, *pdfs(9))
    transaction = Transaction.objects.get()

    edit_with(signed_in, transaction, *pdfs(1))

    assert transaction.attachments.count() == 10
