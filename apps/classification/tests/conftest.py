from decimal import Decimal
from typing import TYPE_CHECKING

from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from apps.accounts.models import Account
    from apps.classification.models import Party, Tag


def move(  # noqa: PLR0913
    when: date,
    source: Account,
    target: Account,
    amount: str,
    *,
    party: Party | None = None,
    tags: Sequence[Tag] = (),
    description: str = "",
) -> Split:
    """Record a one-Split Transaction and return its Split."""
    transaction = Transaction.objects.create(
        date=when, party=party, description=description
    )
    split = transaction.splits.create(
        from_account=source, to_account=target, amount=Decimal(amount)
    )
    split.tags.set(tags)
    return split
