from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.transactions.models import Attachment, Transaction
from apps.transactions.tests.conftest import (
    attach,
    queued_deletes,
    recorded,
    run_queued_deletes,
    stored_names,
    transaction_url,
)

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def record_with_files() -> Transaction:
    transaction = recorded()
    attach(transaction, "one.pdf")
    attach(transaction, "two.pdf")
    return transaction


def test_delete_removes_attachments_and_their_files(signed_in: Client) -> None:
    transaction = record_with_files()
    assert len(stored_names()) == 2

    response = signed_in.post(transaction_url("transaction_delete", transaction))

    assert response["Location"] == reverse("transaction_list")
    assert not Transaction.objects.exists()
    assert not Attachment.objects.exists()
    run_queued_deletes()
    assert stored_names() == []


@pytest.mark.usefixtures("delete_fails")
def test_storage_failure_doesnt_block_the_delete(signed_in: Client) -> None:
    transaction = record_with_files()
    files = stored_names()

    response = signed_in.post(transaction_url("transaction_delete", transaction))

    assert response.status_code == 302
    assert response["Location"] == reverse("transaction_list")
    assert not Transaction.objects.exists()
    assert sorted(queued_deletes()) == files
