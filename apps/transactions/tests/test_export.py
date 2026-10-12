import csv
import io
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party, Tag
from apps.transactions.models import Transaction
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def exported(client: Client, **query: str) -> list[list[str]]:
    response = client.get(reverse("transaction_export"), query)
    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]
    return list(csv.reader(io.StringIO(response.content.decode())))


def test_exports_one_row_per_split(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    household = make_account("Household", "expense")
    transaction = Transaction.objects.create(
        date=date(2026, 3, 1),
        description="Weekly shop",
        party=Party.objects.create(name="Store"),
    )
    food = transaction.splits.create(
        from_account=bank, to_account=groceries, amount=Decimal("60.00")
    )
    food.tags.add(Tag.objects.create(name="food"), Tag.objects.create(name="weekly"))
    transaction.splits.create(
        from_account=bank, to_account=household, amount=Decimal("40.00")
    )

    rows = exported(signed_in)

    assert rows[0] == ["Date", "Party", "Description", "From", "To", "Amount", "Tags"]
    assert sorted(rows[1:]) == [
        [
            "2026-03-01",
            "Store",
            "Weekly shop",
            "Bank",
            "Groceries",
            "60.00",
            "food, weekly",
        ],
        ["2026-03-01", "Store", "Weekly shop", "Bank", "Household", "40.00", ""],
    ]


def test_export_follows_the_filters(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    for description in ("Rent", "Coffee"):
        Transaction.objects.create(
            date=date(2026, 3, 1), description=description
        ).splits.create(from_account=bank, to_account=rent, amount=Decimal(10))

    rows = exported(signed_in, q="coffee")

    assert [row[2] for row in rows[1:]] == ["Coffee"]


def test_list_links_to_export_with_the_filters(signed_in: Client) -> None:
    response = signed_in.get(reverse("transaction_list"), {"q": "rent", "page": "2"})

    assert (
        f'href="{reverse("transaction_export")}?q=rent" hx-boost="false" download'
        in response.content.decode()
    )


def test_export_is_blocked_in_privacy_mode(signed_in: Client) -> None:
    url = reverse("transaction_export")
    turn_on(signed_in)

    response = signed_in.get(url)

    assert response["Location"] == privacy_mode_off_url(url)


def test_privacy_mode_offers_no_export_link(signed_in: Client) -> None:
    turn_on(signed_in)

    response = signed_in.get(reverse("transaction_list"), {"q": "rent"})

    assert reverse("transaction_export") not in response.content.decode()
