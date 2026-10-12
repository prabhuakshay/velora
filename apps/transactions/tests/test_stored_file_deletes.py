from typing import TYPE_CHECKING

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import transaction as db_transaction
from django.urls import reverse

from apps.accounts.merge import AccountMerge
from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Attachment, Transaction
from apps.transactions.tasks import delete_stored_file
from apps.transactions.tests.conftest import (
    attach,
    queued_deletes,
    recorded,
    run_queued_deletes,
    stored_names,
)

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_deleting_an_attachment_queues_its_stored_file_for_deletion() -> None:
    attachment = attach(recorded())
    name = attachment.file.name

    attachment.delete()

    assert queued_deletes() == [name]
    assert stored_names() == [name]
    run_queued_deletes()
    assert stored_names() == []


def test_a_bulk_delete_queues_every_stored_file() -> None:
    transaction = recorded()
    names = [attach(transaction, f"{n}.pdf").file.name for n in range(2)]

    Attachment.objects.all().delete()

    assert set(queued_deletes()) == set(names)


def test_an_attachment_without_a_file_queues_nothing() -> None:
    attachment = attach(recorded())
    Attachment.objects.filter(pk=attachment.pk).update(file="")

    Attachment.objects.all().delete()

    assert queued_deletes() == []


def test_a_rolled_back_delete_queues_nothing_and_keeps_the_file() -> None:
    attachment = attach(recorded())
    pk, name = attachment.pk, attachment.file.name

    def delete_then_fail() -> None:
        with db_transaction.atomic():
            attachment.delete()
            raise RuntimeError

    with pytest.raises(RuntimeError):
        delete_then_fail()

    assert queued_deletes() == []
    assert Attachment.objects.get().pk == pk
    assert stored_names() == [name]


def test_merging_away_a_transaction_queues_its_attachments() -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    transaction = Transaction.objects.create(date="2026-03-01")
    transaction.splits.create(from_account=old_bank, to_account=bank, amount=50)
    name = attach(transaction).file.name

    AccountMerge(old_bank, bank).run()

    assert not Transaction.objects.exists()
    assert queued_deletes() == [name]
    run_queued_deletes()
    assert stored_names() == []


def test_admin_delete_queues_each_attachment(client: Client, superuser: User) -> None:
    transaction = recorded()
    names = [attach(transaction, f"{n}.pdf").file.name for n in range(2)]
    client.force_login(superuser)

    client.post(
        reverse("admin:transactions_transaction_delete", args=[transaction.pk]),
        {"post": "yes"},
    )

    assert not Transaction.objects.exists()
    assert set(queued_deletes()) == set(names)


def test_admin_delete_selected_queues_each_attachment(
    client: Client, superuser: User
) -> None:
    transactions = [recorded("one"), recorded("two")]
    names = [attach(t).file.name for t in transactions]
    client.force_login(superuser)

    client.post(
        reverse("admin:transactions_transaction_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [t.pk for t in transactions],
            "post": "yes",
        },
    )

    assert not Transaction.objects.exists()
    assert set(queued_deletes()) == set(names)


def test_seed_reset_queues_the_attachments_it_wipes() -> None:
    name = attach(recorded()).file.name

    call_command("seed_transactions", months=1, per_month=10, reset=True)

    assert not Attachment.objects.exists()
    assert queued_deletes() == [name]


@pytest.mark.usefixtures("missing_raises")
def test_the_task_counts_a_missing_file_as_deleted() -> None:
    delete_stored_file(name="attachments/gone")

    assert stored_names() == []


@pytest.mark.usefixtures("delete_fails")
def test_the_task_reraises_other_storage_errors_so_it_is_retried() -> None:
    name = default_storage.save("attachments/kept", ContentFile(b""))

    with pytest.raises(OSError, match="storage unavailable"):
        delete_stored_file(name=name)
