from typing import TYPE_CHECKING

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Attachment, Transaction
from apps.transactions.tests.conftest import form_data, stored_names, transaction_url

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def record_with_files(client: Client) -> Transaction:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    client.post(
        reverse("transaction_create"),
        form_data(
            bank,
            groceries,
            attachments=[
                SimpleUploadedFile("one.pdf", b"%PDF one", "application/pdf"),
                SimpleUploadedFile("two.pdf", b"%PDF two", "application/pdf"),
            ],
        ),
    )
    return Transaction.objects.get()


def test_delete_removes_attachments_and_their_files(signed_in: Client) -> None:
    transaction = record_with_files(signed_in)
    assert len(stored_names()) == 2

    response = signed_in.post(transaction_url("transaction_delete", transaction))

    assert response["Location"] == reverse("transaction_list")
    assert not Transaction.objects.exists()
    assert not Attachment.objects.exists()
    assert stored_names() == []


@pytest.mark.usefixtures("delete_fails")
def test_storage_failure_keeps_everything_and_says_so(signed_in: Client) -> None:
    transaction = record_with_files(signed_in)
    files = stored_names()
    url = transaction_url("transaction_delete", transaction)

    response = signed_in.post(url, follow=True)

    assert response.redirect_chain == [(url, 302)]
    assert (
        "Couldn&#x27;t remove attachments from storage; nothing was deleted. "
        "Try again." in response.content.decode()
    )
    assert Transaction.objects.get() == transaction
    assert transaction.attachments.count() == 2
    assert stored_names() == files


@pytest.mark.usefixtures("second_delete_fails")
def test_retrying_after_a_partial_failure_deletes_everything(
    signed_in: Client,
) -> None:
    transaction = record_with_files(signed_in)
    url = transaction_url("transaction_delete", transaction)
    signed_in.post(url)
    assert transaction.attachments.count() == 2
    assert len(stored_names()) == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("transaction_list")
    assert not Transaction.objects.exists()
    assert not Attachment.objects.exists()
    assert stored_names() == []
