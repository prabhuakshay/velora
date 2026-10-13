"""Keeping Statements and their payments in step with the Transactions."""

from typing import TYPE_CHECKING

from apps.accounts.models import Account
from apps.cards.statements import refresh_estimates
from apps.quick_add.models import Draft
from apps.transactions.signals import touched_accounts

if TYPE_CHECKING:
    from apps.transactions.models import Transaction


def remove_posting_draft(instance: Transaction, **_: object) -> None:
    """Remove the Statement payment Draft that posted the deleted Transaction.

    Its Statement can then be proposed a payment again for what is still
    owed, once the card is re-estimated after the deletion.
    """
    if instance.statement_id:
        Draft.objects.filter(
            statement_id=instance.statement_id, transaction=instance
        ).delete()


def refresh_cards(account_ids: set[int], **_: object) -> None:
    """Re-estimate the Statements of the cards among the Accounts."""
    refresh_estimates(*Account.objects.filter(pk__in=account_ids))


def note_touched_accounts(instance: Transaction, **_: object) -> None:
    """Keep the deleted Transaction's Accounts; its Splits are gone once deleted."""
    instance.touched_account_ids = touched_accounts(instance)  # type: ignore[attr-defined]


def refresh_deleted_cards(instance: Transaction, **_: object) -> None:
    """Re-estimate the cards the deleted Transaction touched, after its cascades."""
    refresh_cards(instance.touched_account_ids)  # type: ignore[attr-defined]


def refresh_after_payment(
    instance: Transaction, update_fields: frozenset[str] | None, **_: object
) -> None:
    """Re-estimate the card when a payment is linked to one of its Statements.

    A payment linked to one Statement leaves every other one's estimate.
    Unlinking refreshes the card itself, as it knows the Statement it left.
    """
    if instance.statement_id and update_fields and "statement" in update_fields:
        refresh_estimates(instance.statement.card)  # type: ignore[union-attr]
