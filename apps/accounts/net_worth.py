"""Net Worth: the Asset Balances minus the Liability Balances."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import BALANCE_KINDS, Account, AccountKind


@dataclass(frozen=True)
class NetWorth:
    """The Assets and Liabilities totals behind a Net Worth figure."""

    assets: Decimal
    liabilities: Decimal

    @property
    def total(self) -> Decimal:
        """Net Worth; a Liability's Balance is what is owed, so it subtracts."""
        return self.assets - self.liabilities


def as_of_date(raw: str | None) -> date:
    """The as-of date from a GET value; today when missing, invalid or future."""
    today = timezone.localdate()
    try:
        when = date.fromisoformat(raw or "")
    except ValueError:
        return today
    return min(when, today)


def net_worth(as_of: date) -> NetWorth:
    """Net Worth as of a date: the sum of each Account's value, hidden ones included."""
    # Value is the Balance; an investment Account could supply market value here.
    totals: dict[str, Decimal] = dict.fromkeys(BALANCE_KINDS, Decimal(0))
    included = Account.objects.filter(kind__in=BALANCE_KINDS, include_in_net_worth=True)
    for account in included.with_balance(as_of):
        totals[account.kind] += account.balance
    return NetWorth(
        assets=totals[AccountKind.ASSET], liabilities=totals[AccountKind.LIABILITY]
    )
