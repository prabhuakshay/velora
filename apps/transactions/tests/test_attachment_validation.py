import io
import zipfile
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import (
    attach,
    form_data,
    recorded,
    stored_names,
    transaction_url,
    upload,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

pytestmark = pytest.mark.django_db


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
        ("folded.md", b"<details>Two years</details>", "text/markdown"),
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
        ("quote.docx", b"PK\x03\x04 not really a zip"),
    ],
)
def test_file_whose_content_does_not_match_its_extension_is_rejected(
    signed_in: Client, name: str, content: bytes
) -> None:
    response = create_with(signed_in, upload(name, content))

    assert_rejected(response, f"{name} doesn&#x27;t contain what its file type says.")


def quote_with_header(content: bytes, offset: int, value: bytes) -> bytes:
    """A .docx whose member has bytes changed in its central directory entry."""
    data = zipped({"word/document.xml": content})
    at = data.index(b"PK\x01\x02") + offset
    return data[:at] + value + data[at + len(value) :]


FLAGS, COMPRESSION = 8, 10
DEFLATE = b"\x08\x00"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(quote_with_header(b"<w/>", FLAGS, b"\x01\x00"), id="encrypted"),
        pytest.param(
            quote_with_header(b"<w/>", COMPRESSION, b"\x63\x00"),
            id="unsupported compression",
        ),
        # Stored bytes read as deflate data with an invalid block type.
        pytest.param(
            quote_with_header(b"\xff\xff", COMPRESSION, DEFLATE), id="corrupt data"
        ),
    ],
)
def test_zip_that_cannot_be_read_is_rejected(signed_in: Client, content: bytes) -> None:
    response = create_with(signed_in, upload("quote.docx", content))

    assert_rejected(
        response, "quote.docx doesn&#x27;t contain what its file type says."
    )


MB = 1024 * 1024


TOO_LARGE = "A Transaction&#x27;s Attachments can total at most 10 MB."


def pdf_bytes(size: int) -> bytes:
    return b"%PDF" + b"0" * (size - 4)


def pdf_of(size: int, name: str = "scan.pdf") -> SimpleUploadedFile:
    return upload(name, pdf_bytes(size))


def test_files_totalling_exactly_10_mb_are_accepted(signed_in: Client) -> None:
    response = create_with(
        signed_in, pdf_of(6 * MB, "one.pdf"), pdf_of(4 * MB, "two.pdf")
    )

    assert response["Location"] == reverse("transaction_list")
    assert len(stored_names()) == 2


def test_files_totalling_over_10_mb_are_rejected_naming_the_limit(
    signed_in: Client,
) -> None:
    response = create_with(
        signed_in, pdf_of(6 * MB, "one.pdf"), pdf_of(4 * MB + 1, "two.pdf")
    )

    assert_rejected(response, TOO_LARGE)
    assert "Pick them again." in response.content.decode()


def test_single_file_over_10_mb_is_rejected(signed_in: Client) -> None:
    response = create_with(signed_in, pdf_of(10 * MB + 1))

    assert_rejected(response, TOO_LARGE)
    assert "the most an Attachment can be" not in response.content.decode()


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


def test_edit_counts_existing_attachment_sizes_towards_the_total(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attach(transaction, content=pdf_bytes(6 * MB))
    existing = stored_names()

    response = edit_with(signed_in, transaction, pdf_of(4 * MB + 1))

    assert TOO_LARGE in response.content.decode()
    transaction.refresh_from_db()
    assert transaction.description == ""
    assert transaction.attachments.count() == 1
    assert stored_names() == existing


def test_edit_may_fill_up_to_the_total(signed_in: Client) -> None:
    transaction = recorded()
    attach(transaction, content=pdf_bytes(6 * MB))

    response = edit_with(signed_in, transaction, pdf_of(4 * MB))

    assert response.status_code == 302
    assert transaction.attachments.count() == 2


def over_the_total() -> Transaction:
    """A Transaction whose Attachments already total more than 10 MB."""
    transaction = recorded()
    attach(transaction, content=pdf_bytes(11 * MB))
    return transaction


def test_edit_without_files_of_a_transaction_over_the_total_is_saved(
    signed_in: Client,
) -> None:
    transaction = over_the_total()

    response = edit_with(signed_in, transaction)

    assert response.status_code == 302
    transaction.refresh_from_db()
    assert transaction.description == "Changed"


def test_any_file_added_to_a_transaction_over_the_total_is_rejected(
    signed_in: Client,
) -> None:
    transaction = over_the_total()

    response = edit_with(signed_in, transaction, upload("tiny.pdf", b"%PDF"))

    assert TOO_LARGE in response.content.decode()
    assert transaction.attachments.count() == 1


def test_request_declaring_over_12_mb_is_refused_before_it_is_read(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    response = signed_in.post(
        reverse("transaction_create"),
        form_data(bank, groceries, attachments=[upload("bill.pdf", b"%PDF")]),
        CONTENT_LENGTH=str(12 * MB + 1),
    )

    assert response.status_code == 413
    assert "413.html" in [t.name for t in response.templates]
    page = response.content.decode()
    assert "Files too large" in page
    assert "A Transaction's Attachments can total 10 MB." in page
    assert not Transaction.objects.exists()
    assert stored_names() == []


def test_request_just_under_12_mb_reaches_the_form(signed_in: Client) -> None:
    # Leaves room for the other fields and multipart framing.
    response = create_with(signed_in, pdf_of(12 * MB - 64 * 1024))

    assert_rejected(response, TOO_LARGE)


def test_file_picker_carries_the_limit_for_the_browser_check(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attach(transaction, content=pdf_bytes(3 * MB))

    response = signed_in.get(transaction_url("transaction_edit", transaction))

    page = response.content.decode()
    assert f'data-max-total-bytes="{10 * MB}"' in page
    assert f'data-existing-bytes="{3 * MB}"' in page
    assert f'data-too-large="{TOO_LARGE}"' in page
