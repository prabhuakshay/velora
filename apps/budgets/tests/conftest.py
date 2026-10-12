from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from apps.accounts.models import Account

JUNE = date(2026, 6, 1)
TODAY = date(2026, 6, 15)


def move(when: date, source: Account, destination: Account, amount: str) -> None:
    transaction = Transaction.objects.create(date=when)
    Split.objects.create(
        transaction=transaction,
        from_account=source,
        to_account=destination,
        amount=Decimal(amount),
    )
