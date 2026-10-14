"""What an Account's Reconciliations are checked against (ADR 0011).

An Investment Account that Holds Cash is checked against its Cash, every other
Account against its Balance. The database compares against the Balance, so
for Holds Cash the gap between Balance and Cash is added in Python.
"""

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from apps.investments.valuation import Valuer

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from apps.accounts.models import Account, Reconciliation


def cash_valuer(accounts: Iterable[Account]) -> Valuer:
    """A Valuer of those accounts that Hold Cash, in one query.

    Makes no query when none of them Holds Cash.
    """
    return Valuer([account.pk for account in accounts if account.reconciles_cash])


def cash_gaps(
    account: Account, days: Iterable[date], valuer: Valuer | None = None
) -> dict[date, Decimal]:
    """The account's Balance less its Cash at the end of each day.

    Zero for an account that doesn't Hold Cash. Given no Valuer, it loads one.
    """
    days = set(days)
    if not account.reconciles_cash or not days:
        return dict.fromkeys(days, Decimal(0))
    if valuer is None:
        valuer = Valuer([account.pk], max(days))
    opened = cast("date", account.opening_balance_date)
    return {day: -valuer.cash(account.pk, opened, Decimal(0), day) for day in days}


def checked_on(account: Account, when: date) -> Decimal:
    """What a Reconciliation on the day is checked against: Cash or Balance."""
    return account.balance_on(when) - cash_gaps(account, [when])[when]


def checked(
    account: Account, reconciliations: Iterable[Reconciliation]
) -> list[Reconciliation]:
    """The account's Reconciliations from with_difference(), off by against Cash.

    Only an account that Holds Cash needs the difference corrected.
    """
    found = list(reconciliations)
    gaps = cash_gaps(account, (r.date for r in found))
    for reconciliation in found:
        reconciliation.difference += gaps[reconciliation.date]
    return found


def latest_matching(
    account: Account, before: date | None = None
) -> Reconciliation | None:
    """The account's latest Reconciliation still matching, before the day if given."""
    reconciliations = account.reconciliations.order_by("-date")
    if before is not None:
        reconciliations = reconciliations.filter(date__lt=before)
    if not account.reconciles_cash:
        return reconciliations.matching().first()
    return next(
        (
            r
            for r in checked(account, reconciliations.with_difference())
            if not r.difference
        ),
        None,
    )
