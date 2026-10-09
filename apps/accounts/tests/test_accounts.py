from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.forms import AccountForm
from apps.accounts.models import Account

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db

KINDS = ["expense", "income"]


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("url_name", "pk"),
    [("account_list", None), ("account_create", None), ("account_edit", 1)],
)
def test_anonymous_is_redirected_to_login(
    client: Client, kind: str, url_name: str, pk: int | None
) -> None:
    kwargs = {"kind": kind} if pk is None else {"kind": kind, "pk": pk}
    url = reverse(url_name, kwargs=kwargs)

    response = client.post(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def list_page(client: Client, kind: str) -> str:
    return client.get(reverse("account_list", kwargs={"kind": kind})).content.decode()


def accounts_group_tag(body: str) -> str:
    before_summary = body[: body.index("Accounts\n")]
    return before_summary.rsplit("<details", 1)[1].split(">", maxsplit=1)[0]


def test_sidebar_links_to_accounts_in_a_closed_group(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "open" not in accounts_group_tag(body)
    for kind in KINDS:
        assert reverse("account_list", kwargs={"kind": kind}) in body


@pytest.mark.parametrize("kind", KINDS)
def test_sidebar_accounts_group_is_open_on_its_pages(
    signed_in: Client, kind: str
) -> None:
    assert "open" in accounts_group_tag(list_page(signed_in, kind))


@pytest.mark.parametrize("kind", KINDS)
def test_create_account_stores_kind_from_page(signed_in: Client, kind: str) -> None:
    url = reverse("account_create", kwargs={"kind": kind})
    assert signed_in.get(url).status_code == 200

    response = signed_in.post(url, {"name": "Groceries", "notes": "Food"})

    assert response["Location"] == reverse("account_list", kwargs={"kind": kind})
    account = Account.objects.get()
    assert (account.name, account.notes, account.kind) == ("Groceries", "Food", kind)


def test_list_shows_only_its_kind_sorted_by_name_ignoring_case(
    signed_in: Client,
) -> None:
    for name in ["rent", "Fuel", "groceries", "Books"]:
        Account.objects.create(name=name, kind="expense")
    Account.objects.create(name="Salary", kind="income")

    body = list_page(signed_in, "expense")

    positions = [body.index(n) for n in ["Books", "Fuel", "groceries", "rent"]]
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
    assert b"already exists" in response.content


def test_edit_renames_and_updates_notes(signed_in: Client) -> None:
    account = Account.objects.create(name="Grocries", kind="expense", notes="old")

    response = signed_in.post(
        reverse("account_edit", kwargs={"kind": "expense", "pk": account.pk}),
        {"name": "Groceries", "notes": "new"},
    )

    assert response["Location"] == reverse("account_list", kwargs={"kind": "expense"})
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


@pytest.mark.parametrize("path", ["/accounts/savings/", "/accounts/savings/new/"])
def test_unsupported_kind_is_not_found(signed_in: Client, path: str) -> None:
    assert signed_in.get(path).status_code == 404
