"""Dividends: Income Transactions into the account that receives them (ADR 0012)."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

from apps.accounts.models import Account, InvestmentMode
from apps.investments.replay import DIVIDEND
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from apps.investments.models import InvestmentEvent

# Where each investment mode's Dividends are paid.
RECEIVER: dict[str, Callable[[Account], Account]] = {
    InvestmentMode.HOLDS_CASH: lambda account: account,
    InvestmentMode.DIRECT: lambda account: cast("Account", account.invests_into),
}


def receiving_account(account: Account) -> Account:
    """The Account an Investment Account's Dividends are paid into."""
    return RECEIVER[account.investment_mode](account)


def posts_transaction(event: InvestmentEvent) -> bool:
    """Whether the event is a Dividend that moves ledger money.

    One on or before the Investment Account's Opening Balance date is already
    inside that Opening Balance, so it builds history only.
    """
    opened = event.account.opening_balance_date
    return event.kind == DIVIDEND and opened is not None and event.date > opened


def income_account_of(event: InvestmentEvent) -> Account | None:
    """The Income Account the event's Transaction came from, if it has one."""
    if event.transaction is None:
        return None
    split = event.transaction.splits.select_related("from_account").first()
    return None if split is None else split.from_account


def transaction_forms(event: InvestmentEvent, income: Account) -> TransactionForms:
    """The Dividend's Transaction, new or its existing one, as forms to check."""
    existing = event.transaction or Transaction()
    split = existing.splits.first() if existing.pk else None
    data: dict[str, Any] = {
        "date": event.date.isoformat(),
        "party": existing.party_id or "",
        "description": f"Dividend from {event.instrument}",
        "splits-TOTAL_FORMS": "1",
        "splits-INITIAL_FORMS": "1" if split else "0",
        "splits-0-id": split.pk if split else "",
        "splits-0-from_account": income.pk,
        "splits-0-to_account": receiving_account(event.account).pk,
        "splits-0-amount": event.amount,
    }
    return TransactionForms(data, instance=existing)


@contextmanager
def linking(event: InvestmentEvent, forms: TransactionForms) -> Iterator[None]:
    """Wrap saving the Transaction so the event is saved linked to it."""
    yield
    event.transaction = forms.form.instance
    event.save()


def save_unlinked(event: InvestmentEvent) -> None:
    """Save an event that moves no ledger money, deleting any Transaction it had."""
    stale = event.transaction
    event.transaction = None
    event.save()
    if stale is not None:
        stale.delete()
