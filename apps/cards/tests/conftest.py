from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.cards.models import CardEMI
from apps.transactions.models import Transaction


def make_card(
    name: str = "HDFC card",
    *,
    statement_day: int = 15,
    due_day: int = 5,
    pays_from: Account | None = None,
) -> Account:
    """A credit card closing on the 15th and due on the 5th."""
    card = make_account(name, "liability")
    card.statement_day = statement_day
    card.due_day = due_day
    card.pays_from = pays_from or make_account(f"{name} bank", "asset")
    card.save()
    return card


def record(source: Account, destination: Account, amount: str, on: date) -> Transaction:
    transaction = Transaction.objects.create(date=on)
    transaction.splits.create(
        from_account=source, to_account=destination, amount=Decimal(amount)
    )
    return transaction


@pytest.fixture
def card() -> Account:
    return make_card()


@pytest.fixture
def groceries() -> Account:
    return make_account("Groceries", "expense")


def make_card_emi(  # noqa: PLR0913
    card: Account,
    *,
    principal: str = "100000",
    months: int = 12,
    annual_rate: str = "15",
    processing_fee: str = "0",
    bought_on: date | None = None,
    first_statement: date | None = None,
    interest_account: Account | None = None,
) -> CardEMI:
    """A Card EMI on a purchase of the principal, bought 20 Aug 2026.

    Its first installment is billed on the Statement closing 15 Sep 2026.
    """
    bought_on = bought_on or date(2026, 8, 20)
    store, _ = Account.objects.get_or_create(name="Store", kind="expense")
    return CardEMI.objects.create(
        purchase=record(card, store, principal, bought_on),
        card=card,
        principal=Decimal(principal),
        months=months,
        annual_rate=Decimal(annual_rate),
        processing_fee=Decimal(processing_fee),
        first_statement=first_statement or date(2026, 9, 15),
        interest_account=interest_account
        or Account.objects.get_or_create(name="EMI interest", kind="expense")[0],
    )
