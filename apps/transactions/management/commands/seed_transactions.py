"""Bulk-create dummy data for local development."""

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.management.base import BaseCommand
from django.db import connection, transaction as db_transaction
from django.utils import timezone

from apps.accounts.models import Account, AccountKind
from apps.classification.models import Party, Tag
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from argparse import ArgumentParser

ASSETS = {
    "HDFC Savings": 500_000,
    "SBI Savings": 150_000,
    "Cash": 10_000,
    "PPF (SBI)": 400_000,
    "Zerodha Equity": 300_000,
    "Mutual Funds (Groww)": 350_000,
}
LIABILITIES = {"ICICI Amazon Pay Credit Card": 0}
INCOMES = ["Salary", "Freelance", "Dividends", "Savings Interest"]
EXPENSES = [
    "Groceries",
    "Dining Out",
    "Fuel",
    "Electricity",
    "Mobile & Internet",
    "Household Help",
    "Shopping",
    "Medical",
    "Travel",
    "Entertainment",
    "Insurance",
    "Gifts",
    "Personal Care",
    "Subscriptions",
    "Society Maintenance",
]
PARTIES = [
    "BigBasket",
    "Swiggy",
    "Zomato",
    "Amazon",
    "Flipkart",
    "Indian Oil",
    "BESCOM",
    "Airtel",
    "Jio",
    "Apollo Pharmacy",
    "IndiGo",
    "BookMyShow",
    "Netflix",
    "DMart",
    "Reliance Fresh",
    "Uber",
    "Ola",
    "LIC",
    "Acme Corp",
]
TAGS = {"Work": "blue", "Family": "green", "Trip": "amber", "Reimbursable": "violet"}

# Wiped by --reset; CASCADE also clears Attachment rows and history.
RESET_TABLES = [
    "transactions_transaction",
    "transactions_split",
    "accounts_account",
    "classification_party",
    "classification_tag",
    "accounts_historicalaccount",
    "classification_historicalparty",
    "classification_historicaltag",
    "transactions_historicaltransaction",
    "transactions_historicalsplit",
    "transactions_historicalsplit_tags",
]


class Command(BaseCommand):
    """Seed the dev database; amounts keep every Asset and Net Worth positive."""

    help = "Create dummy Accounts, Parties, Tags and Transactions."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add --months, --per-month and --reset."""
        parser.add_argument("--months", type=int, default=12)
        parser.add_argument("--per-month", type=int, default=1000)
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete ALL Transactions, Accounts, Parties and Tags first.",
        )

    @db_transaction.atomic
    def handle(
        self,
        *_args: object,
        months: int,
        per_month: int,
        reset: bool,
        **_options: object,
    ) -> None:
        """Create the data, after wiping old data when --reset is passed."""
        if reset:
            with connection.cursor() as cursor:
                # TRUNCATE refuses while deferred FK checks from this transaction pend.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(f"TRUNCATE {', '.join(RESET_TABLES)} CASCADE")

        today = timezone.localdate()
        first = date(today.year, today.month, 1)
        for _ in range(months):
            first = (first - timedelta(days=1)).replace(day=1)
        opened = first - timedelta(days=1)

        bank, card = self._balance_accounts(opened)
        incomes = [self._account(n, AccountKind.INCOME) for n in INCOMES]
        expenses = [self._account(n, AccountKind.EXPENSE) for n in EXPENSES]
        parties = [self._named(Party, n) for n in PARTIES]
        tags = [self._named(Tag, n, color=c) for n, c in TAGS.items()]

        rows = self._rows(first, months, per_month, (bank, card, incomes, expenses))
        txns = Transaction.objects.bulk_create(
            Transaction(
                date=day,
                party=random.choice(parties) if random.random() < 0.8 else None,
                description=f"Dummy {to.name.lower()}",
            )
            for day, _, to, _ in rows
        )
        splits = Split.objects.bulk_create(
            Split(transaction=txn, from_account=frm, to_account=to, amount=amount)
            for txn, (_, frm, to, amount) in zip(txns, rows, strict=True)
        )
        through = Split.tags.through
        through.objects.bulk_create(
            through(split_id=s.pk, tag_id=tag.pk)
            for s in splits
            if random.random() < 0.3
            for tag in random.sample(tags, k=random.randint(1, 2))
        )
        self.stdout.write(f"Created {len(txns)} Transactions.")

    def _rows(
        self,
        first: date,
        months: int,
        per_month: int,
        accounts: tuple[Account, Account, list[Account], list[Account]],
    ) -> list[tuple[date, Account, Account, Decimal]]:
        bank, card, incomes, expenses = accounts
        rows: list[tuple[date, Account, Account, Decimal]] = []
        for _ in range(months):
            days = ((first + timedelta(days=32)).replace(day=1) - first).days
            spent = on_card = Decimal(0)
            for _ in range(per_month - 3):
                amount = Decimal(str(round(random.lognormvariate(5.5, 1.0), 2)))
                amount = max(amount, Decimal("0.01"))
                source = card if random.random() < 0.4 else bank
                day = first + timedelta(days=random.randrange(days))
                rows.append((day, source, random.choice(expenses), amount))
                spent += amount
                if source is card:
                    on_card += amount
            # Income is 90-170% of spending so Net Worth trends up but some
            # months dip; the worst case (-10% a month) can't drain the bank.
            share = Decimal(str(random.uniform(0.45, 0.85)))
            pay = (spent * share).quantize(Decimal("0.01"))
            rows.append((first, random.choice(incomes), bank, pay))
            rows.append((first + timedelta(days=14), random.choice(incomes), bank, pay))
            rows.append((first + timedelta(days=days - 1), bank, card, on_card))
            first += timedelta(days=days)
        return rows

    def _balance_accounts(self, opened: date) -> tuple[Account, Account]:
        def make(name: str, kind: str, balance: int) -> Account:
            return self._account(
                name, kind, opening_balance=balance, opening_balance_date=opened
            )

        bank, *_ = [make(n, AccountKind.ASSET, b) for n, b in ASSETS.items()]
        card, *_ = [make(n, AccountKind.LIABILITY, b) for n, b in LIABILITIES.items()]
        return bank, card

    def _account(self, name: str, kind: str, **defaults: object) -> Account:
        account, _ = Account.objects.get_or_create(
            name=name, kind=kind, defaults=defaults
        )
        return account

    def _named[T: (Party, Tag)](
        self, model: type[T], name: str, **defaults: object
    ) -> T:
        obj, _ = model.objects.get_or_create(name=name, defaults=defaults)
        return obj
