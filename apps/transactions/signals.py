"""Telling other apps a Transaction's Splits were saved, and cleaning up files."""

from django.dispatch import Signal

from apps.transactions.models import Attachment, Split, Transaction
from apps.transactions.tasks import delete_stored_file

# Sent with `account_ids`: every Account the Splits touched, before and after.
splits_saved = Signal()


def touched_accounts(transaction: Transaction) -> set[int]:
    """The ids of the Accounts the Transaction's saved Splits go from or to."""
    # By id, as an unsaved Transaction can't be asked for its Splits.
    pairs = Split.objects.filter(transaction_id=transaction.pk).values_list(
        "from_account_id", "to_account_id"
    )
    return {pk for pair in pairs for pk in pair}


def queue_file_delete(instance: Attachment, **_: object) -> None:
    """Queue the deleted Attachment's stored file for deletion.

    Deferred on Django's connection, so the job commits or rolls back with
    the row's delete and the file is never removed before the commit.
    """
    if instance.file.name:
        delete_stored_file.defer(name=instance.file.name)
