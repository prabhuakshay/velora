from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.forms import ExpenseAccountForm
from apps.budget.models import ExpenseAccount

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_expense_account(name: str, **fields: object) -> ExpenseAccount:
    return ExpenseAccount.objects.create(name=name, **fields)


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def list_page(client: Client, query: str = "") -> str:
    return client.get(reverse("expense_account_list") + query).content.decode()


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("expense_account_list", []),
        ("expense_account_create", []),
        ("expense_account_edit", [1]),
        ("expense_account_delete", [1]),
        ("expense_account_merge", [1]),
        ("expense_account_hide", [1]),
        ("expense_account_unhide", [1]),
    ],
)
def test_anonymous_is_redirected_to_login(
    client: Client, url_name: str, args: list[int]
) -> None:
    url = reverse(url_name, args=args)

    response = client.post(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_index_links_to_expense_accounts(signed_in: Client) -> None:
    response = signed_in.get(reverse("index"))

    assert reverse("expense_account_list").encode() in response.content


def test_create_expense_account_with_notes(signed_in: Client) -> None:
    assert signed_in.get(reverse("expense_account_create")).status_code == 200

    response = signed_in.post(
        reverse("expense_account_create"),
        {"name": "Walmart", "notes": "Card ending 1234"},
    )

    assert response["Location"] == reverse("expense_account_list")
    expense_account = ExpenseAccount.objects.get()
    assert (
        expense_account.name,
        expense_account.notes,
        expense_account.hidden,
    ) == ("Walmart", "Card ending 1234", False)


def test_notes_are_optional(signed_in: Client) -> None:
    response = signed_in.post(reverse("expense_account_create"), {"name": "Walmart"})

    assert response.status_code == 302
    assert ExpenseAccount.objects.get().notes == ""


def test_list_sorted_by_name_ignoring_case(signed_in: Client) -> None:
    for name in ["walmart", "Acme", "employer", "Bakery"]:
        make_expense_account(name)

    body = list_page(signed_in)

    positions = [body.index(n) for n in ["Acme", "Bakery", "employer", "walmart"]]
    assert positions == sorted(positions)


def test_create_duplicate_name_in_any_case_shows_error(signed_in: Client) -> None:
    make_expense_account("Walmart")

    response = signed_in.post(reverse("expense_account_create"), {"name": "walmart"})

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert ExpenseAccount.objects.count() == 1


def test_edit_renames_and_updates_notes(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmrt", notes="old")

    response = signed_in.post(
        reverse("expense_account_edit", args=[expense_account.pk]),
        {"name": "Walmart", "notes": "new"},
    )

    assert response["Location"] == reverse("expense_account_list")
    expense_account.refresh_from_db()
    assert (expense_account.name, expense_account.notes) == ("Walmart", "new")


def test_edit_form_renders_current_values(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmart", notes="Card ending 1234")

    response = signed_in.get(reverse("expense_account_edit", args=[expense_account.pk]))

    assert b"Walmart" in response.content
    assert b"Card ending 1234" in response.content


def test_edit_keeping_own_name_in_other_case_is_allowed(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmart")

    response = signed_in.post(
        reverse("expense_account_edit", args=[expense_account.pk]), {"name": "WALMART"}
    )

    assert response.status_code == 302


def test_edit_to_existing_name_shows_error(signed_in: Client) -> None:
    make_expense_account("Walmart")
    expense_account = make_expense_account("Acme")

    response = signed_in.post(
        reverse("expense_account_edit", args=[expense_account.pk]), {"name": "walmart"}
    )

    assert b"already exists" in response.content
    expense_account.refresh_from_db()
    assert expense_account.name == "Acme"


def test_hide_removes_expense_account_from_default_list(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmart")

    response = signed_in.post(
        reverse("expense_account_hide", args=[expense_account.pk])
    )

    assert response["Location"] == reverse("expense_account_list")
    assert "Walmart" not in list_page(signed_in)


def test_show_hidden_reveals_dimmed_expense_account_with_unhide(
    signed_in: Client,
) -> None:
    expense_account = make_expense_account("Walmart", hidden=True)

    content = list_page(signed_in, "?show_hidden=1")

    assert "Walmart" in content
    assert "opacity-50" in content
    assert (
        reverse("expense_account_unhide", args=[expense_account.pk]) + "?show_hidden=1"
        in content
    )


def test_unhide_restores_expense_account(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmart", hidden=True)

    response = signed_in.post(
        reverse("expense_account_unhide", args=[expense_account.pk]) + "?show_hidden=1"
    )

    assert response["Location"] == reverse("expense_account_list") + "?show_hidden=1"
    assert "Walmart" in list_page(signed_in)


def test_edit_form_can_set_hidden(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmart")

    signed_in.post(
        reverse("expense_account_edit", args=[expense_account.pk]),
        {"name": "Walmart", "hidden": "on"},
    )

    assert "Walmart" not in list_page(signed_in)


@pytest.mark.parametrize("name", ["expense_account_hide", "expense_account_unhide"])
def test_hide_actions_reject_get(signed_in: Client, name: str) -> None:
    expense_account = make_expense_account("Walmart")

    assert signed_in.get(reverse(name, args=[expense_account.pk])).status_code == 405


def test_delete_requires_confirmation_then_deletes(signed_in: Client) -> None:
    expense_account = make_expense_account("Walmart")
    url = reverse("expense_account_delete", args=[expense_account.pk])

    assert signed_in.get(url).status_code == 200
    assert ExpenseAccount.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("expense_account_list")
    assert not ExpenseAccount.objects.exists()


def test_changes_are_recorded_against_the_acting_user(
    signed_in: Client, user: User
) -> None:
    signed_in.post(reverse("expense_account_create"), {"name": "Walmart"})
    expense_account = ExpenseAccount.objects.get()
    signed_in.post(
        reverse("expense_account_edit", args=[expense_account.pk]), {"name": "Acme"}
    )
    signed_in.post(reverse("expense_account_hide", args=[expense_account.pk]))
    signed_in.post(reverse("expense_account_delete", args=[expense_account.pk]))

    records = list(ExpenseAccount.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "~", "~", "-"]
    assert {r.history_user for r in records} == {user}


def test_admin_shows_expense_accounts_with_history(
    client: Client, superuser: User
) -> None:
    client.force_login(superuser)
    expense_account = make_expense_account("Walmart")

    assert (
        client.get(reverse("admin:budget_expenseaccount_changelist")).status_code == 200
    )
    history = reverse("admin:budget_expenseaccount_history", args=[expense_account.pk])
    assert client.get(history).status_code == 200


def test_concurrent_duplicate_expense_account_name_shows_error(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_expense_account("Walmart")
    # Simulates the race: validation passed before the other request committed.
    monkeypatch.setattr(ExpenseAccountForm, "clean_name", lambda self: "Walmart")
    monkeypatch.setattr(ExpenseAccount, "validate_constraints", lambda *_, **__: None)

    response = signed_in.post(reverse("expense_account_create"), {"name": "walmart"})

    assert response.status_code == 200
    assert "already" in response.content.decode()
