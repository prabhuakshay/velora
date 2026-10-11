from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party, Tag
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


@pytest.fixture
def accounts() -> dict[str, Account]:
    return {
        "bank": make_account("Bank", "asset"),
        "card": make_account("Card", "liability"),
        "groceries": make_account("Groceries", "expense"),
        "rent": make_account("Rent", "expense"),
    }


def record(
    description: str,
    source: Account,
    destination: Account,
    amount: str = "100",
    **fields: Any,
) -> Transaction:
    fields.setdefault("date", date(2026, 3, 1))
    transaction = Transaction.objects.create(description=description, **fields)
    transaction.splits.create(
        from_account=source, to_account=destination, amount=Decimal(amount)
    )
    return transaction


def shown(client: Client, **query: str | int) -> set[str]:
    """The descriptions of the Transactions the list shows for the query."""
    response = client.get(reverse("transaction_list"), query)
    page = response.context["page"]
    return {transaction.description for transaction in page}


def test_search_matches_description_party_account_and_tag(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    bank, card = accounts["bank"], accounts["card"]
    record("Weekly shop", bank, accounts["groceries"])
    record(
        "Lunch", card, accounts["groceries"], party=Party.objects.create(name="Toit")
    )
    record("April", bank, accounts["rent"])
    tagged = record("Taxi", card, accounts["groceries"])
    tagged.splits.get().tags.add(Tag.objects.create(name="Goa trip"))

    assert shown(signed_in, q="weekly") == {"Weekly shop"}
    assert shown(signed_in, q="toit") == {"Lunch"}
    assert shown(signed_in, q="rent") == {"April"}
    assert shown(signed_in, q="goa") == {"Taxi"}


def test_account_filter_matches_either_side_of_a_split(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    bank = accounts["bank"]
    record("Paid out", bank, accounts["groceries"])
    record("Paid in", accounts["card"], bank)
    record("Elsewhere", accounts["card"], accounts["rent"])

    assert shown(signed_in, account=bank.pk) == {"Paid out", "Paid in"}


def test_party_and_tag_filters(signed_in: Client, accounts: dict[str, Account]) -> None:
    bank, groceries = accounts["bank"], accounts["groceries"]
    shop = Party.objects.create(name="Big Bazaar")
    trip = Tag.objects.create(name="Trip")
    record("At the shop", bank, groceries, party=shop)
    record("On the trip", bank, groceries).splits.get().tags.add(trip)
    record("Neither", bank, groceries)

    assert shown(signed_in, party=shop.pk) == {"At the shop"}
    assert shown(signed_in, tag=trip.pk) == {"On the trip"}


def test_date_range_includes_both_ends(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    bank, groceries = accounts["bank"], accounts["groceries"]
    for day in (1, 5, 10, 15):
        record(f"Day {day}", bank, groceries, date=date(2026, 3, day))

    assert shown(signed_in, start="2026-03-05", end="2026-03-10") == {
        "Day 5",
        "Day 10",
    }


def test_amount_range_uses_the_transaction_total(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    bank = accounts["bank"]
    record("Small", bank, accounts["groceries"], "50")
    split_up = record("Split up", bank, accounts["groceries"], "300")
    split_up.splits.create(
        from_account=bank, to_account=accounts["rent"], amount=Decimal(400)
    )
    record("Large", bank, accounts["rent"], "900")

    assert shown(signed_in, min_total="600", max_total="800") == {"Split up"}


def test_filters_combine(signed_in: Client, accounts: dict[str, Account]) -> None:
    bank, card, groceries = accounts["bank"], accounts["card"], accounts["groceries"]
    record("Groceries early", bank, groceries, date=date(2026, 3, 1))
    record("Groceries late", bank, groceries, date=date(2026, 3, 20))
    record("Card late", card, groceries, date=date(2026, 3, 20))

    assert shown(signed_in, account=bank.pk, start="2026-03-10") == {"Groceries late"}


def test_invalid_filter_is_reported_and_ignored(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    record("Kept", accounts["bank"], accounts["groceries"])

    response = signed_in.get(reverse("transaction_list"), {"start": "not a date"})

    assert {t.description for t in response.context["page"]} == {"Kept"}
    assert "Enter a valid date." in response.content.decode()


def test_no_match_says_so_and_offers_to_clear(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    record("Lunch", accounts["bank"], accounts["groceries"])

    body = signed_in.get(reverse("transaction_list"), {"q": "dinner"}).content.decode()

    assert "No Transactions match." in body
    assert "0 matching Transactions" in body


def test_pagination_keeps_the_filters(
    signed_in: Client, accounts: dict[str, Account]
) -> None:
    bank, groceries = accounts["bank"], accounts["groceries"]
    for day in range(1, 28):
        record(f"Shop {day:02}", bank, groceries, date=date(2026, 3, day))

    first = signed_in.get(reverse("transaction_list"), {"q": "shop"})
    second = signed_in.get(reverse("transaction_list"), {"q": "shop", "page": "2"})

    assert "?page=2&amp;q=shop" in first.content.decode()
    assert len(second.context["page"]) == 2
