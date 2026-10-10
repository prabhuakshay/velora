"""Keeping Statements unpaid when the Transaction paying them goes."""

from typing import TYPE_CHECKING

from apps.cards.models import Statement
from apps.cards.statements import sync_payment_draft
from apps.quick_add.models import Draft

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
