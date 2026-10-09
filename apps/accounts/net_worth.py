"""Net Worth: the Asset Balances minus the Liability Balances."""

from dataclasses import dataclass
from decimal import Decimal

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


def net_worth() -> NetWorth:
    """Net Worth today: the sum of each Account's value, hidden ones included."""
    # Value is the Balance; an investment Account could supply market value here.
    totals: dict[str, Decimal] = dict.fromkeys(BALANCE_KINDS, Decimal(0))
    included = Account.objects.filter(kind__in=BALANCE_KINDS, include_in_net_worth=True)
    for account in included.with_balance():
        totals[account.kind] += account.balance
    return NetWorth(
        assets=totals[AccountKind.ASSET], liabilities=totals[AccountKind.LIABILITY]
    )
