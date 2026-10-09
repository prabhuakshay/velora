import re
from typing import TYPE_CHECKING

import pytest
from django.db import OperationalError
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import (
    fail_next_commit,
    form_data,
    stored_names,
    upload,
)

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

UUID_KEY = re.compile(r"attachments/[0-9a-f]{32}")


def test_create_stores_a_file_as_an_attachment(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    response = signed_in.post(
        reverse("transaction_create"),
        form_data(
            bank, groceries, attachments=upload("receipt.pdf", b"%PDF-1.4 receipt")
        ),
    )

    assert response["Location"] == reverse("transaction_list")
    attachment = Transaction.objects.get().attachments.get()
    assert (attachment.original_name, attachment.content_type, attachment.size) == (
        "receipt.pdf",
        "application/pdf",
        16,
    )
    assert UUID_KEY.fullmatch(str(attachment.file.name))
    assert stored_names() == [attachment.file.name]
    assert attachment.file.read() == b"%PDF-1.4 receipt"


def test_create_stores_several_files_as_attachments_in_order(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    signed_in.post(
        reverse("transaction_create"),
        form_data(
            bank,
            groceries,
            attachments=[
                upload("bill.png", b"\x89PNG page one"),
                upload("warranty.txt", b"two years"),
            ],
        ),
    )

    attachments = list(Transaction.objects.get().attachments.all())
    assert [a.original_name for a in attachments] == ["bill.png", "warranty.txt"]
    assert stored_names() == sorted(str(a.file.name) for a in attachments)
    assert len(set(stored_names())) == 2


def test_invalid_form_stores_no_files_and_asks_to_pick_them_again(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    response = signed_in.post(
        reverse("transaction_create"),
        form_data(bank, groceries, "-5", attachments=upload("receipt.pdf", b"%PDF")),
    )

    assert response.status_code == 200
    assert "Pick them again" in response.content.decode()
    assert not Transaction.objects.exists()
    assert stored_names() == []


def test_invalid_form_without_files_does_not_mention_files(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    response = signed_in.post(
        reverse("transaction_create"), form_data(bank, groceries, "-5")
    )

    assert "Pick them again" not in response.content.decode()


@pytest.mark.usefixtures("second_save_fails")
def test_storage_failure_partway_leaves_no_transaction_or_files(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    with pytest.raises(OSError, match="storage unavailable"):
        signed_in.post(
            reverse("transaction_create"),
            form_data(
                bank,
                groceries,
                attachments=[
                    upload("one.pdf", b"%PDF one"),
                    upload("two.pdf", b"%PDF two"),
                ],
            ),
        )

    assert not Transaction.objects.exists()
    assert stored_names() == []


@pytest.mark.django_db(transaction=True)
def test_failed_commit_leaves_no_transaction_or_files(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    fail_next_commit(monkeypatch)

    with pytest.raises(OperationalError, match="connection lost"):
        signed_in.post(
            reverse("transaction_create"),
            form_data(bank, groceries, attachments=upload("one.pdf", b"%PDF one")),
        )

    assert not Transaction.objects.exists()
    assert stored_names() == []
