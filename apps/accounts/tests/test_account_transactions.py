from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import account_url, list_page, make_account
from apps.classification.models import Party
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def record(
    when: date, source: Account, destination: Account, amount: str, description: str
) -> Transaction:
    transaction = Transaction.objects.create(date=when, description=description)
    transaction.splits.create(
        from_account=source, to_account=destination, amount=Decimal(amount)
    )
    return transaction


def view_page(client: Client, account: Account, query: str = "") -> str:
    url = account_url("account_transactions", account) + query
    return client.get(url).content.decode()


def test_list_links_to_each_account_view(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")

    assert account_url("account_transactions", bank) in list_page(signed_in, "asset")


def test_view_shows_only_transactions_touching_the_account(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    shop = Party.objects.create(name="Big Bazaar")
    weekly = record(date(2026, 3, 1), bank, groceries, "850.50", "Weekly")
    weekly.party = shop
    weekly.save()
    record(date(2026, 3, 2), cash, groceries, "20", "Snacks")

    body = view_page(signed_in, bank)

    for text in ["1 Mar 2026", "Big Bazaar", "Weekly", "Groceries", "850.50"]:
        assert text in body
    assert "Snacks" not in body


def test_view_shows_only_splits_touching_the_account(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")
    trip = record(date(2026, 3, 1), bank, groceries, "100", "Trip")
    trip.splits.create(from_account=cash, to_account=fuel, amount=Decimal(50))

    body = view_page(signed_in, bank)

    assert "Groceries" in body
    assert "Fuel" not in body


def test_view_shows_balance_for_balance_kinds(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    record(date(2026, 3, 1), bank, groceries, "100", "Weekly")

    assert "Balance ₹-100.00" in view_page(signed_in, bank)
    assert "Balance" not in view_page(signed_in, groceries)


def test_view_is_paginated_newest_first(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    for day in range(1, 27):
        record(date(2026, 3, day), bank, groceries, "1", f"Day {day:02}")

    first, second = view_page(signed_in, bank), view_page(signed_in, bank, "?page=2")

    assert "Day 26" in first
    assert "Day 01" not in first
    assert "Day 01" in second
    assert "?page=2" in first


def test_view_of_another_kind_is_not_found(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    url = account_url("account_transactions", bank).replace("asset", "expense")

    assert signed_in.get(url).status_code == 404
