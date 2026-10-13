"""The Transaction a Direct Investment Account's Buy or Sell posts (ADR 0012).

A Buy is paid from the account's Pays from, for its amount plus charges; a
Sell pays its net proceeds into its Pays into. Events on or before the
Opening Balance date post nothing: they are inside the Opening Balance.
"""

from typing import TYPE_CHECKING, Any

from apps.investments import dividends
from apps.investments.replay import BUY, DIVIDEND, SELL
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms

if TYPE_CHECKING:
    from decimal import Decimal

    from apps.accounts.models import Account
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


def moves_money(event: InvestmentEvent) -> bool:
    """Whether the event posts a Transaction: a Direct trade or a Dividend."""
    return posts_transaction(event) or dividends.posts_transaction(event)


def route(
    event: InvestmentEvent, income: Account | None = None
) -> tuple[int | None, int | None, Decimal | None]:
    """The From and To Account ids and amount of the Split moving its money.

    A Dividend comes from its Income Account, which may not be known yet.
    """
    account = event.account
    if event.kind == DIVIDEND:
        receiver = dividends.receiving_account(account)
        return (income.pk if income else None), receiver.pk, event.amount
    amount = None if event.amount is None else money_moved(event)
    if event.kind == BUY:
        return account.invests_from_id, account.pk, amount
    return account.pk, account.invests_into_id, amount


def transaction_forms(event: InvestmentEvent) -> TransactionForms | None:
    """The event's linked Transaction as it should now be, or None for none.

    The existing linked Transaction, if any, is edited in place: its Splits
    are replaced, and its Party, Attachments and Statement stay.
    """
    if not posts_transaction(event):
        return None
    linked = event.transaction or Transaction()
    old = list(linked.splits.all()) if linked.pk else []
    source, destination, amount = route(event)
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
        f"splits-{len(old)}-amount": amount,
    }
    return TransactionForms(data, instance=linked)
