"""Telling other apps a Transaction's Splits were saved."""

from django.dispatch import Signal

from apps.transactions.models import Split, Transaction

# Sent with `account_ids`: every Account the Splits touched, before and after.
splits_saved = Signal()


def touched_accounts(transaction: Transaction) -> set[int]:
    """The ids of the Accounts the Transaction's saved Splits go from or to."""
    # By id, as an unsaved Transaction can't be asked for its Splits.
    pairs = Split.objects.filter(transaction_id=transaction.pk).values_list(
        "from_account_id", "to_account_id"
    )
    return {pk for pair in pairs for pk in pair}
