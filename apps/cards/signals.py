"""Keeping Statements and their payments in step with the Transactions."""

from typing import TYPE_CHECKING

from apps.accounts.models import Account
from apps.cards.models import Statement
from apps.cards.statements import refresh_estimates, sync_payment_draft
from apps.quick_add.models import Draft
from apps.transactions.signals import touched_accounts

if TYPE_CHECKING:
    from apps.transactions.models import Transaction


def reopen_statement(instance: Transaction, **_: object) -> None:
    """Put the Statement the deleted Transaction paid back to unpaid.

    The Draft that posted the Transaction is removed, so its payment can be
    proposed again.
    """
    statement = Statement.objects.filter(transaction=instance).first()
    if statement is None:
        return
    Draft.objects.filter(statement=statement).delete()
    statement.transaction = None
    statement.save(update_fields=["transaction"])
    sync_payment_draft(statement)


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
    instance: Statement, update_fields: frozenset[str] | None, **_: object
) -> None:
    """Re-estimate the card when a payment is linked to one of its Statements.

    A payment linked to one Statement leaves every other one's estimate.
    Unlinking happens only as the payment is deleted, which refreshes the
    card once it is gone.
    """
    if instance.transaction_id and update_fields and "transaction" in update_fields:
        refresh_estimates(instance.card)
