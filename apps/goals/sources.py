"""What a Goal can be allocated from, and what each source is worth now.

A source is an Asset Account, valued at its Balance or, for an Investment
Account, its Market Value, or one Holding, valued at its Market Value.
"""

from typing import TYPE_CHECKING

from django.db.models.functions import Lower

from apps.accounts.models import Account
from apps.investments.models import InvestmentEvent
from apps.investments.valuation import account_value

if TYPE_CHECKING:
    from collections.abc import Collection
    from decimal import Decimal


def source_key(account: int, instrument: int | None = None) -> str:
    """The key naming an account (instrument None) or a Holding in it."""
    if instrument is None:
        return f"account:{account}"
    return f"holding:{account}:{instrument}"


def parse_source(key: str) -> tuple[int, int | None] | None:
    """The account and instrument a key names, or None if it is malformed."""
    match key.split(":"):
        case ["account", account] if account.isdigit():
            return int(account), None
        case ["holding", account, instrument] if (
            account.isdigit() and instrument.isdigit()
        ):
            return int(account), int(instrument)
    return None


def source_choices() -> list[tuple[str, list[tuple[str, str]]]]:
    """Visible Asset Accounts, and every Instrument held in an Investment Account."""
    accounts = [
        (source_key(pk), name)
        for pk, name in Account.objects.filter(kind="asset", hidden=False)
        .order_by(Lower("name"))
        .values_list("pk", "name")
    ]
    holdings = [
        (source_key(account, instrument), f"{fund} in {held_in}")
        for account, instrument, fund, held_in in InvestmentEvent.objects.filter(
            account__hidden=False
        )
        .order_by(Lower("instrument__name"), Lower("account__name"))
        .values_list("account", "instrument", "instrument__name", "account__name")
        .distinct()
    ]
    return [("Accounts", accounts), ("Holdings", holdings)]


def source_values(accounts: Collection[int]) -> dict[str, Decimal]:
    """What each of the accounts, and each Holding in them, is worth now."""
    values: dict[str, Decimal] = {}
    for account in Account.objects.filter(pk__in=accounts).with_balance():
        if not account.is_investment:
            values[source_key(account.pk)] = account.balance
            continue
        worth = account_value(account, account.balance)
        values[source_key(account.pk)] = worth.market_value
        for row in worth.holdings:
            values[source_key(account.pk, row.instrument.pk)] = row.market_value
    return values
