"""Dividends: Income Transactions into the account that receives them (ADR 0012)."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from apps.accounts.models import Account, InvestmentMode
from apps.investments.replay import DIVIDEND

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from apps.investments.models import InvestmentEvent
    from apps.quick_add.models import Draft
    from apps.transactions.models import Transaction
    from apps.transactions.recording import TransactionForms

RECEIVER: dict[str, Callable[[Account], Account]] = {
    InvestmentMode.HOLDS_CASH: lambda account: account,
    InvestmentMode.DIRECT: lambda account: cast("Account", account.invests_into),
}


def receiving_account(account: Account) -> Account:
    """The Account an Investment Account's Dividends are paid into."""
    return RECEIVER[account.investment_mode](account)


def posts_dividend(event: InvestmentEvent) -> bool:
    """Whether the event is a Dividend that moves ledger money.

    One on or before the Investment Account's Opening Balance date is already
    inside that Opening Balance, so it builds history only.
    """
    opened = event.account.opening_balance_date
    return event.kind == DIVIDEND and opened is not None and event.date > opened


def income_account(paid: Transaction | Draft | None) -> Account | None:
    """The Income Account a Dividend's Transaction or Draft is paid from, if any.

    That is the From of its one Split.
    """
    if paid is None or paid.pk is None:
        return None
    split = paid.splits.select_related("from_account").first()
    return None if split is None else split.from_account


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
