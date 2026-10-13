"""The Transaction a Direct Investment Account's Buy or Sell posts (ADR 0012).

A Buy is paid from the account's Pays from, for its amount plus charges; a
Sell pays its net proceeds into its Pays into. Events on or before the
Opening Balance date post nothing: they are inside the Opening Balance.
"""

from typing import TYPE_CHECKING, Any

from apps.investments.replay import BUY, SELL
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms

if TYPE_CHECKING:
    from decimal import Decimal

    from apps.investments.models import InvestmentEvent


def posts_transaction(event: InvestmentEvent) -> bool:
    """Whether the event moves money in the ledger."""
    account = event.account
    opened = account.opening_balance_date
    return (
        account.is_direct
        and event.kind in {BUY, SELL}
        and opened is not None
        and event.date > opened
    )


def money_moved(event: InvestmentEvent) -> Decimal:
    """What a Buy cost with its charges, or what a Sell brought in after them."""
    amount = event.amount or 0
    if event.kind == BUY:
        return amount + event.charges
    return amount - event.charges


def transaction_forms(event: InvestmentEvent) -> TransactionForms | None:
    """The event's linked Transaction as it should now be, or None for none.

    The existing linked Transaction, if any, is edited in place: its Splits
    are replaced, and its Party, Attachments and Statement stay.
    """
    if not posts_transaction(event):
        return None
    linked = event.transaction or Transaction()
    old = list(linked.splits.all()) if linked.pk else []
    account = event.account
    source, destination = (
        (account.invests_from_id, account.pk)
        if event.kind == BUY
        else (account.pk, account.invests_into_id)
    )
    data: dict[str, Any] = {
        "date": event.date.isoformat(),
        "party": linked.party_id or "",
        "description": f"{event.get_kind_display()} {event.instrument}",
        "splits-TOTAL_FORMS": len(old) + 1,
        "splits-INITIAL_FORMS": len(old),
    }
    for index, split in enumerate(old):
        data |= {
            f"splits-{index}-id": split.pk,
            f"splits-{index}-from_account": split.from_account_id,
            f"splits-{index}-to_account": split.to_account_id,
            f"splits-{index}-amount": split.amount,
            f"splits-{index}-DELETE": "on",
        }
    data |= {
        f"splits-{len(old)}-from_account": source,
        f"splits-{len(old)}-to_account": destination,
        f"splits-{len(old)}-amount": money_moved(event),
    }
    return TransactionForms(data, instance=linked)
