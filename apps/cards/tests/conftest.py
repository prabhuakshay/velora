from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from datetime import date

    from apps.accounts.models import Account


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
