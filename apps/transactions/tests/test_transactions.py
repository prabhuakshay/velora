from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.transactions.models import Split, Transaction
from apps.transactions.tests.conftest import form_data, transaction_url

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_create_records_transaction_with_one_split(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    shop = Party.objects.create(name="Big Bazaar")

    response = signed_in.post(
        reverse("transaction_create"),
        form_data(bank, groceries, "850.50", party=shop.pk, description="Weekly"),
    )

    assert response["Location"] == reverse("transaction_list")
    transaction = Transaction.objects.get()
    assert (transaction.date, transaction.party, transaction.description) == (
        date(2026, 3, 1),
        shop,
        "Weekly",
    )
    split = transaction.splits.get()
    assert (split.from_account, split.to_account, split.amount) == (
        bank,
        groceries,
        Decimal("850.50"),
    )


def record(
    when: date, source: Account, destination: Account, amount: str, **fields: Any
) -> Transaction:
    transaction = Transaction.objects.create(date=when, **fields)
    transaction.splits.create(
        from_account=source, to_account=destination, amount=Decimal(amount)
    )
    return transaction


def list_page(client: Client, query: str = "") -> str:
    return client.get(reverse("transaction_list") + query).content.decode()


def test_sidebar_links_to_transactions(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert reverse("transaction_list") in body


def test_list_shows_date_party_description_accounts_and_amount(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    shop = Party.objects.create(name="Big Bazaar")
    record(
        date(2026, 3, 1), bank, groceries, "850.50", party=shop, description="Weekly"
    )

    body = list_page(signed_in)

    for text in ["1 Mar 2026", "Big Bazaar", "Weekly", "Bank", "Groceries", "850.50"]:
        assert text in body


def test_list_is_newest_date_first_then_newest_created(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    record(date(2026, 3, 1), bank, groceries, "1", description="First added")
    record(date(2026, 3, 5), bank, groceries, "1", description="Newest date")
    record(date(2026, 3, 1), bank, groceries, "1", description="Last added")

    body = list_page(signed_in)

    positions = [
        body.index(text) for text in ["Newest date", "Last added", "First added"]
    ]
    assert positions == sorted(positions)


def test_list_is_paginated(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    for day in range(1, 27):
        record(date(2026, 3, day), bank, groceries, "1", description=f"Day {day:02}")

    first, second = list_page(signed_in), list_page(signed_in, "?page=2")

    assert "Day 26" in first
    assert "Day 01" not in first
    assert "Day 01" in second
    assert "Day 26" not in second
    assert "?page=2" in first


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("transaction_list", []),
        ("transaction_create", []),
        ("transaction_split_row", []),
        ("transaction_edit", [1]),
        ("transaction_delete", [1]),
    ],
)
def test_anonymous_is_redirected_to_login(
    client: Client, url_name: str, args: list[int]
) -> None:
    url = reverse(url_name, args=args)

    response = client.post(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_new_form_defaults_date_to_today(signed_in: Client) -> None:
    body = signed_in.get(reverse("transaction_create")).content.decode()

    assert f'name="date" value="{timezone.localdate().isoformat()}"' in body


def test_party_and_description_are_optional(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")

    signed_in.post(reverse("transaction_create"), form_data(bank, cash))

    transaction = Transaction.objects.get()
    assert (transaction.party, transaction.description) == (None, "")


def test_edit_changes_transaction_and_its_split(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    rent = make_account("Rent", "expense")
    transaction = record(date(2026, 3, 1), bank, groceries, "100")
    split = transaction.splits.get()
    url = transaction_url("transaction_edit", transaction)
    assert "Groceries" in signed_in.get(url).content.decode()

    response = signed_in.post(
        url,
        form_data(bank, rent, "25000", split_id=split.pk, date="2026-03-02"),
    )

    assert response["Location"] == reverse("transaction_list")
    transaction.refresh_from_db()
    assert transaction.date == date(2026, 3, 2)
    split = transaction.splits.get()
    assert (split.to_account, split.amount) == (rent, Decimal(25000))


def test_delete_requires_confirmation_then_deletes(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    transaction = record(date(2026, 3, 1), bank, groceries, "100", description="Milk")
    url = transaction_url("transaction_delete", transaction)

    confirmation = signed_in.get(url).content.decode()
    assert "Milk" in confirmation
    assert reverse("transaction_list") in confirmation
    assert Transaction.objects.exists()

    response = signed_in.post(url)

    assert response["Location"] == reverse("transaction_list")
    assert not Transaction.objects.exists()
    assert not Split.objects.exists()


def test_changes_are_kept_in_history(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    signed_in.post(reverse("transaction_create"), form_data(bank, groceries))
    transaction = Transaction.objects.get()

    signed_in.post(transaction_url("transaction_delete", transaction))

    assert Transaction.history.filter(history_type="-").count() == 1
    assert Split.history.filter(history_type="-").count() == 1
