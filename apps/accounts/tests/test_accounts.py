from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.forms import AccountForm
from apps.accounts.models import Account
from apps.accounts.tests.conftest import KINDS, list_page, list_url

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", KINDS)
def test_create_account_stores_kind_from_page(signed_in: Client, kind: str) -> None:
    url = reverse("account_create", kwargs={"kind": kind})
    assert signed_in.get(url).status_code == 200

    response = signed_in.post(
        url,
        {
            "name": "Groceries",
            "notes": "Food",
            "opening_balance": "0",
            "opening_balance_date": "2026-01-01",
        },
    )

    assert response["Location"] == list_url(kind)
    account = Account.objects.get()
    assert (account.name, account.notes, account.kind) == ("Groceries", "Food", kind)


def test_list_shows_only_its_kind_sorted_by_name_ignoring_case(
    signed_in: Client,
) -> None:
    for name in ["rent", "Fuel", "groceries", "Books"]:
        Account.objects.create(name=name, kind="expense")
    Account.objects.create(name="Salary", kind="income")

    body = list_page(signed_in, "expense")

    positions = [body.index(f">{n}<") for n in ["Books", "Fuel", "groceries", "rent"]]
    assert positions == sorted(positions)
    assert "Salary" not in body


def test_create_duplicate_name_in_any_case_shows_error(signed_in: Client) -> None:
    Account.objects.create(name="Groceries", kind="expense")

    response = signed_in.post(
        reverse("account_create", kwargs={"kind": "expense"}), {"name": "groceries"}
    )

    assert b"Another Expense Account already has this name." in response.content
    assert Account.objects.count() == 1


def test_same_name_is_allowed_in_another_kind(signed_in: Client) -> None:
    Account.objects.create(name="Interest", kind="expense")

    response = signed_in.post(
        reverse("account_create", kwargs={"kind": "income"}), {"name": "interest"}
    )

    assert response.status_code == 302
    assert Account.objects.filter(kind="income", name="interest").exists()


def test_concurrent_duplicate_name_shows_error(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    Account.objects.create(name="Groceries", kind="expense")
    # Simulates the race: validation passed before the other request committed.
    monkeypatch.setattr(AccountForm, "clean_name", lambda self: "Groceries")
    monkeypatch.setattr(Account, "validate_constraints", lambda *_, **__: None)

    response = signed_in.post(
        reverse("account_create", kwargs={"kind": "expense"}), {"name": "groceries"}
    )

    assert response.status_code == 200
    assert b"Another Expense Account already has this name." in response.content


def test_edit_renames_and_updates_notes(signed_in: Client) -> None:
    account = Account.objects.create(name="Grocries", kind="expense", notes="old")

    response = signed_in.post(
        reverse("account_edit", kwargs={"kind": "expense", "pk": account.pk}),
        {"name": "Groceries", "notes": "new"},
    )

    assert response["Location"] == list_url("expense")
    account.refresh_from_db()
    assert (account.name, account.notes) == ("Groceries", "new")


def test_edit_keeping_own_name_in_other_case_is_allowed(signed_in: Client) -> None:
    account = Account.objects.create(name="groceries", kind="expense")

    response = signed_in.post(
        reverse("account_edit", kwargs={"kind": "expense", "pk": account.pk}),
        {"name": "Groceries"},
    )

    assert response.status_code == 302
    account.refresh_from_db()
    assert account.name == "Groceries"


def test_edit_cannot_change_kind(signed_in: Client) -> None:
    account = Account.objects.create(name="Salary", kind="income")

    signed_in.post(
        reverse("account_edit", kwargs={"kind": "income", "pk": account.pk}),
        {"name": "Salary", "kind": "expense"},
    )

    account.refresh_from_db()
    assert account.kind == "income"


def test_edit_url_with_another_kind_is_not_found(signed_in: Client) -> None:
    account = Account.objects.create(name="Salary", kind="income")

    url = reverse("account_edit", kwargs={"kind": "expense", "pk": account.pk})

    assert signed_in.get(url).status_code == 404


def test_changes_are_recorded_against_the_acting_user(
    signed_in: Client, user: User
) -> None:
    signed_in.post(
        reverse("account_create", kwargs={"kind": "expense"}), {"name": "Rent"}
    )
    account = Account.objects.get()
    signed_in.post(
        reverse("account_edit", kwargs={"kind": "expense", "pk": account.pk}),
        {"name": "House rent"},
    )

    records = list(Account.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "~"]
    assert {r.history_user for r in records} == {user}


def test_admin_lists_accounts_with_kind_and_history(
    client: Client, superuser: User
) -> None:
    client.force_login(superuser)
    account = Account.objects.create(name="Salary", kind="income")

    changelist = client.get(reverse("admin:accounts_account_changelist"))
    assert b"Salary" in changelist.content
    assert b"Income" in changelist.content
    history = reverse("admin:accounts_account_history", args=[account.pk])
    assert client.get(history).status_code == 200


def test_list_is_paginated_keeping_show_hidden(signed_in: Client) -> None:
    for number in range(26):
        Account.objects.create(name=f"Account {number:02}", kind="expense")

    first = signed_in.get(list_url("expense") + "?show_hidden=1").content.decode()
    second = list_page(signed_in, "expense", "?page=2")

    assert "Account 24" in first
    assert "Account 25" not in first
    assert "Account 25" in second
    assert "?page=2&amp;show_hidden=1" in first
