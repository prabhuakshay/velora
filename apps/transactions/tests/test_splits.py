from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Tag
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import row, split_rows, transaction_url

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_create_records_several_splits_with_their_own_tags(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    household = make_account("Household", "expense")
    trip = Tag.objects.create(name="trip-goa")

    response = signed_in.post(
        reverse("transaction_create"),
        split_rows(
            row(bank, groceries, "800", tags=[trip.pk]),
            row(bank, household, "200"),
        ),
    )

    assert response["Location"] == reverse("transaction_list")
    splits = Transaction.objects.get().splits.order_by("amount")
    assert [(s.to_account, s.amount, list(s.tags.all())) for s in splits] == [
        (household, Decimal(200), []),
        (groceries, Decimal(800), [trip]),
    ]


def record(source: Account, *destinations: Account) -> Transaction:
    transaction = Transaction.objects.create(date=date(2026, 3, 1))
    for destination in destinations:
        transaction.splits.create(
            from_account=source, to_account=destination, amount=Decimal(100)
        )
    return transaction


def test_edit_adds_changes_and_removes_splits(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    household = make_account("Household", "expense")
    rent = make_account("Rent", "expense")
    transaction = record(bank, groceries, household)
    kept, removed = transaction.splits.order_by("pk")

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(
            row(bank, groceries, "150", id=kept.pk),
            row(bank, household, "100", id=removed.pk, DELETE="on"),
            row(bank, rent, "900"),
            initial=2,
        ),
    )

    assert response["Location"] == reverse("transaction_list")
    splits = transaction.splits.order_by("amount")
    assert [(s.to_account, s.amount) for s in splits] == [
        (groceries, Decimal(150)),
        (rent, Decimal(900)),
    ]


def test_removing_every_split_is_rejected(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    transaction = record(bank, groceries)
    split = transaction.splits.get()

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(row(bank, groceries, id=split.pk, DELETE="on"), initial=1),
    )

    assert "Add at least one Split." in response.content.decode()
    assert transaction.splits.exists()


def test_errors_appear_on_the_offending_split_row(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    salary = make_account("Salary", "income")

    response = signed_in.post(
        reverse("transaction_create"),
        split_rows(row(bank, groceries), row(bank, salary)),
    )

    body = response.content.decode()
    error = body.index("An Income Account can only be a source.")
    assert body.index('name="splits-1-id"') < error
    assert body.index('name="splits-1-from_account"') > error
    assert not Transaction.objects.exists()


def test_opening_balance_date_is_checked_for_every_split(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    card = make_account("Card", "liability")
    card.opening_balance_date = date(2026, 3, 15)
    card.save()

    response = signed_in.post(
        reverse("transaction_create"),
        split_rows(row(bank, groceries), row(card, groceries)),
    )

    assert "Opening Balance date of Card" in response.content.decode()
    assert not Transaction.objects.exists()


def test_removed_split_is_not_checked_against_opening_balance(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    card = make_account("Card", "liability")
    card.opening_balance_date = date(2026, 3, 15)
    card.save()
    transaction = record(bank, groceries)
    split = transaction.splits.get()

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(
            row(bank, groceries, id=split.pk),
            row(card, groceries, DELETE="on"),
            initial=1,
        ),
    )

    assert response["Location"] == reverse("transaction_list")
    assert transaction.splits.count() == 1


def test_hidden_tags_are_left_out_of_new_transactions_but_kept_when_editing(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    old_trip = Tag.objects.create(name="trip-ooty", hidden=True)
    Tag.objects.create(name="trip-kochi", hidden=True)
    transaction = record(bank, groceries)
    split = transaction.splits.get()
    split.tags.add(old_trip)
    url = transaction_url("transaction_edit", transaction)

    new_entry = signed_in.get(reverse("transaction_create")).content.decode()
    editing = signed_in.get(url).content.decode()

    assert "trip-ooty" not in new_entry
    assert "trip-ooty" in editing
    assert "trip-kochi" not in editing
    response = signed_in.post(
        url,
        split_rows(row(bank, groceries, id=split.pk, tags=[old_trip.pk]), initial=1),
    )
    assert response["Location"] == reverse("transaction_list")
    assert list(split.tags.all()) == [old_trip]


def test_tag_changes_are_kept_in_history(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    trip = Tag.objects.create(name="trip-goa")
    transaction = record(bank, groceries)
    split = transaction.splits.get()

    signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(row(bank, groceries, id=split.pk, tags=[trip.pk]), initial=1),
    )

    latest = split.history.latest()
    assert [tagged.tag for tagged in latest.tags.all()] == [trip]


def test_add_split_returns_a_blank_row_and_bumps_the_row_count(
    signed_in: Client,
) -> None:
    make_account("Old bank", "asset", hidden=True)
    make_account("Bank", "asset")

    body = signed_in.get(
        reverse("transaction_split_row"), {"splits-TOTAL_FORMS": "2"}
    ).content.decode()

    assert 'name="splits-2-from_account"' in body
    assert 'name="splits-2-DELETE"' in body
    assert 'name="splits-TOTAL_FORMS" value="3"' in body
    assert "Bank" in body
    assert "Old bank" not in body


def test_add_split_treats_a_non_decimal_count_as_zero(signed_in: Client) -> None:
    body = signed_in.get(
        reverse("transaction_split_row"), {"splits-TOTAL_FORMS": "²"}
    ).content.decode()

    assert 'name="splits-0-from_account"' in body


def test_form_has_an_add_split_control(signed_in: Client) -> None:
    body = signed_in.get(reverse("transaction_create")).content.decode()

    assert reverse("transaction_split_row") in body


def test_list_shows_every_account_and_the_total(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    household = make_account("Household", "expense")
    record(bank, groceries, household)

    body = signed_in.get(reverse("transaction_list")).content.decode()

    for text in ["Bank", "Groceries", "Household", "₹200.00"]:
        assert text in body


SHARED_SIDE_ERROR = "Splits must share a From or a To Account."


def test_splits_differing_on_both_sides_are_rejected(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")

    response = signed_in.post(
        reverse("transaction_create"),
        split_rows(row(bank, groceries), row(cash, fuel), description="Weekend run"),
    )

    body = response.content.decode()
    assert body.count(SHARED_SIDE_ERROR) == 1
    assert body.index(SHARED_SIDE_ERROR) < body.index('name="splits-0-id"')
    assert "Weekend run" in body
    assert not Transaction.objects.exists()


@pytest.mark.parametrize("side", ["from", "to"])
def test_splits_sharing_one_side_are_saved(signed_in: Client, side: str) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    rows = (
        [row(bank, groceries), row(bank, cash)]
        if side == "from"
        else [row(bank, groceries), row(cash, groceries)]
    )

    response = signed_in.post(reverse("transaction_create"), split_rows(*rows))

    assert response["Location"] == reverse("transaction_list")
    assert Transaction.objects.get().splits.count() == 2


def test_splits_with_the_same_accounts_and_different_tags_are_saved(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    trip = Tag.objects.create(name="trip-goa")

    response = signed_in.post(
        reverse("transaction_create"),
        split_rows(row(bank, groceries, "800", tags=[trip.pk]), row(bank, groceries)),
    )

    assert response["Location"] == reverse("transaction_list")
    assert Transaction.objects.get().splits.count() == 2


def test_edit_keeping_splits_on_both_sides_is_rejected(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")
    transaction = record(bank, groceries)
    split = transaction.splits.get()

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(row(bank, groceries, id=split.pk), row(cash, fuel), initial=1),
    )

    assert SHARED_SIDE_ERROR in response.content.decode()
    assert transaction.splits.count() == 1


def test_removed_split_is_ignored_by_the_shared_side_rule(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")
    transaction = record(bank, groceries)
    split = transaction.splits.get()

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(
            row(bank, groceries, id=split.pk),
            row(cash, fuel, DELETE="on"),
            initial=1,
        ),
    )

    assert response["Location"] == reverse("transaction_list")
    assert transaction.splits.count() == 1


def test_removed_split_is_ignored_when_another_split_has_an_error(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    cash = make_account("Cash", "asset")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")
    salary = make_account("Salary", "income")
    transaction = record(bank, groceries)
    split = transaction.splits.get()

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(
            row(bank, groceries, id=split.pk),
            row(cash, fuel, DELETE="on"),
            row(bank, salary),
            initial=1,
        ),
    )

    body = response.content.decode()
    assert "An Income Account can only be a source." in body
    assert SHARED_SIDE_ERROR not in body


def test_split_with_a_missing_account_is_not_checked_for_a_shared_side(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")

    response = signed_in.post(
        reverse("transaction_create"),
        split_rows(row(bank, groceries), row(bank, fuel, from_account="")),
    )

    body = response.content.decode()
    assert "This field is required." in body
    assert SHARED_SIDE_ERROR not in body
