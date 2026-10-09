from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def record(when: date, party: Party | None, description: str) -> Transaction:
    transaction = Transaction.objects.create(
        date=when, party=party, description=description
    )
    transaction.splits.create(
        from_account=make_account(f"From {description}", "asset"),
        to_account=make_account(f"To {description}", "expense"),
        amount=Decimal("12.50"),
    )
    return transaction


def view_page(client: Client, party: Party, query: str = "") -> str:
    url = reverse("party_transactions", args=[party.pk]) + query
    return client.get(url).content.decode()


def test_list_links_to_each_party_view(signed_in: Client) -> None:
    shop = Party.objects.create(name="Big Bazaar")

    body = signed_in.get(reverse("party_list")).content.decode()

    assert reverse("party_transactions", args=[shop.pk]) in body


def test_view_shows_only_the_partys_transactions(signed_in: Client) -> None:
    shop = Party.objects.create(name="Big Bazaar")
    other = Party.objects.create(name="Corner Shop")
    record(date(2026, 3, 1), shop, "Weekly")
    record(date(2026, 3, 2), other, "Snacks")
    record(date(2026, 3, 3), None, "Salary")

    body = view_page(signed_in, shop)

    for text in ["1 Mar 2026", "Weekly", "From Weekly", "To Weekly", "12.50"]:
        assert text in body
    assert "Snacks" not in body
    assert "Salary" not in body


def test_view_is_paginated_newest_first(signed_in: Client) -> None:
    shop = Party.objects.create(name="Big Bazaar")
    for day in range(1, 27):
        record(date(2026, 3, day), shop, f"Day {day:02}")

    first, second = view_page(signed_in, shop), view_page(signed_in, shop, "?page=2")

    assert "Day 26" in first
    assert "Day 01" not in first
    assert "Day 01" in second


def test_view_of_missing_party_is_not_found(signed_in: Client) -> None:
    url = reverse("party_transactions", args=[999])

    assert signed_in.get(url).status_code == 404
