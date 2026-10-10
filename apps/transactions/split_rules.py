"""The rules every set of Splits follows, wherever it is entered.

Transactions, Drafts from Quick Add, admin edits and Schedule templates all
check their Splits here, so the rules and their wording stay the same.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from django.utils.formats import date_format

from apps.accounts.models import BALANCE_KINDS, Account

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

Kind = Account.Kind

SAME_ACCOUNT = "A Split cannot go from an Account to itself."
NO_SHARED_ACCOUNT = "Splits must share a From or a To Account."


def direction_error(source: Account, destination: Account) -> str | None:
    """Why a Split may not move money between these Accounts, if it may not."""
    if destination.kind == Kind.INCOME:
        return "An Income Account can only be a source."
    if source.kind == Kind.INCOME and destination.kind == Kind.EXPENSE:
        return "A Split cannot go from an Income Account to an Expense Account."
    if source.kind == Kind.EXPENSE and destination.kind not in BALANCE_KINDS:
        return (
            "An Expense Account can only be a source in a Refund to an Asset "
            "or Liability Account."
        )
    return None


def accounts_error(source: Account, destination: Account) -> str | None:
    """Why one Split may not go between these Accounts, if it may not."""
    if source == destination:
        return SAME_ACCOUNT
    return direction_error(source, destination)


def shared_account_error(pairs: Iterable[tuple[object, object]]) -> str | None:
    """Why these Splits, as (From, To) pairs, don't belong in one Transaction."""
    pairs = list(pairs)
    sources = {source for source, _ in pairs}
    destinations = {destination for _, destination in pairs}
    if len(sources) > 1 and len(destinations) > 1:
        return NO_SHARED_ACCOUNT
    return None


def opening_balance_error(account: Account, when: date) -> str | None:
    """Why a Split on this date may not use the Account, if it may not."""
    if not account.opens_after(when):
        return None
    started = date_format(account.opening_balance_date, "j M Y")  # type: ignore[arg-type]
    return (
        f"The date cannot be before the Opening Balance date of {account} ({started})."
    )


def known_total(amounts: Iterable[Decimal | None]) -> Decimal | None:
    """The amounts added up, or None while any is open or there are none."""
    amounts = list(amounts)
    known = [amount for amount in amounts if amount is not None]
    if not known or len(known) < len(amounts):
        return None
    return sum(known, Decimal(0))
