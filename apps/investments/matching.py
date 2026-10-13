"""Finding the Transaction the user already recorded for an Investment Event."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.db.models import Count

from apps.accounts.models import AccountKind
from apps.investments import dividends, ledger
from apps.investments.replay import BUY, DIVIDEND
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from apps.investments.models import InvestmentEvent

TOLERANCE = timedelta(days=3)


def moves_ledger_money(event: InvestmentEvent) -> bool:
    """Whether the event has a Transaction: a later Direct Buy/Sell or Dividend."""
    return ledger.posts_transaction(event) or dividends.posts_transaction(event)


def _split(event: InvestmentEvent) -> dict[str, Any]:
    account = event.account
    if event.kind == DIVIDEND:
        return {
            "from_account__kind": AccountKind.INCOME,
            "to_account": dividends.receiving_account(account),
            "amount": event.amount,
        }
    source, destination = (
        (account.invests_from_id, account.pk)
        if event.kind == BUY
        else (account.pk, account.invests_into_id)
    )
    return {
        "from_account_id": source,
        "to_account_id": destination,
        "amount": ledger.money_moved(event),
    }


def matching_transaction(event: InvestmentEvent) -> Transaction | None:
    """The nearest unlinked one-Split Transaction moving the event's money.

    It must be between the same Accounts (any Income Account for a Dividend),
    for the same amount and within three days of the event.
    """
    candidates = (
        Transaction.objects.filter(
            investment_event__isnull=True,
            date__range=(event.date - TOLERANCE, event.date + TOLERANCE),
        )
        .annotate(split_count=Count("splits", distinct=True))
        .filter(
            split_count=1,
            **{f"splits__{name}": value for name, value in _split(event).items()},
        )
    )
    return min(
        candidates,
        key=lambda match: (abs(match.date - event.date), match.pk),
        default=None,
    )
