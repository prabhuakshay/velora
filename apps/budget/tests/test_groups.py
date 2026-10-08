from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import CategoryGroup

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_group(
    owner: User, name: str, kind: str = CategoryGroup.Kind.EXPENSE
) -> CategoryGroup:
    return CategoryGroup.objects.create(owner=owner, name=name, kind=kind)


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("category_list", []),
        ("group_create", []),
        ("group_edit", [1]),
        ("group_delete", [1]),
    ],
)
def test_anonymous_is_redirected_to_login(
    client: Client, url_name: str, args: list[int]
) -> None:
    url = reverse(url_name, args=args)

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_index_links_to_categories(signed_in: Client) -> None:
    response = signed_in.get(reverse("index"))

    assert reverse("category_list").encode() in response.content


def test_list_orders_expense_before_income_each_alphabetical(
    signed_in: Client, user: User
) -> None:
    make_group(user, "Salary", CategoryGroup.Kind.INCOME)
    make_group(user, "Food")
    make_group(user, "Bonus", CategoryGroup.Kind.INCOME)
    make_group(user, "Housing")

    body = signed_in.get(reverse("category_list")).content.decode()

    positions = [body.index(n) for n in ["Food", "Housing", "Bonus", "Salary"]]
    assert positions == sorted(positions)


def test_list_hides_other_users_groups(signed_in: Client, other_user: User) -> None:
    make_group(other_user, "Secret")

    response = signed_in.get(reverse("category_list"))

    assert b"Secret" not in response.content


def test_create_group(signed_in: Client, user: User) -> None:
    assert signed_in.get(reverse("group_create")).status_code == 200

    response = signed_in.post(
        reverse("group_create"), {"name": "Food", "kind": "EXPENSE"}
    )

    assert response["Location"] == reverse("category_list")
    group = CategoryGroup.objects.get()
    assert (group.owner, group.name, group.kind) == (user, "Food", "EXPENSE")


def test_create_duplicate_name_in_any_case_shows_error(
    signed_in: Client, user: User
) -> None:
    make_group(user, "Food")

    response = signed_in.post(
        reverse("group_create"), {"name": "fOOD", "kind": "EXPENSE"}
    )

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert CategoryGroup.objects.count() == 1


def test_different_users_may_share_a_name(signed_in: Client, other_user: User) -> None:
    make_group(other_user, "Food")

    response = signed_in.post(
        reverse("group_create"), {"name": "Food", "kind": "EXPENSE"}
    )

    assert response.status_code == 302
    assert CategoryGroup.objects.count() == 2


def test_edit_renames_and_changes_kind(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")

    response = signed_in.post(
        reverse("group_edit", args=[group.pk]), {"name": "Pay", "kind": "INCOME"}
    )

    assert response.status_code == 302
    group.refresh_from_db()
    assert (group.name, group.kind) == ("Pay", "INCOME")


def test_edit_keeping_own_name_is_allowed(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")

    response = signed_in.post(
        reverse("group_edit", args=[group.pk]), {"name": "food", "kind": "INCOME"}
    )

    assert response.status_code == 302


def test_edit_to_existing_name_shows_error(signed_in: Client, user: User) -> None:
    make_group(user, "Food")
    group = make_group(user, "Rent")

    response = signed_in.post(
        reverse("group_edit", args=[group.pk]), {"name": "food", "kind": "EXPENSE"}
    )

    assert b"already exists" in response.content
    group.refresh_from_db()
    assert group.name == "Rent"


def test_edit_form_renders(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")

    response = signed_in.get(reverse("group_edit", args=[group.pk]))

    assert b"Food" in response.content


def test_delete_requires_confirmation_then_deletes(
    signed_in: Client, user: User
) -> None:
    group = make_group(user, "Food")
    url = reverse("group_delete", args=[group.pk])

    assert signed_in.get(url).status_code == 200
    assert CategoryGroup.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("category_list")
    assert CategoryGroup.objects.count() == 0


@pytest.mark.parametrize("url_name", ["group_edit", "group_delete"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_other_users_group_is_not_found(
    signed_in: Client, other_user: User, url_name: str, method: str
) -> None:
    group = make_group(other_user, "Food")

    response = getattr(signed_in, method)(reverse(url_name, args=[group.pk]))

    assert response.status_code == 404
    assert CategoryGroup.objects.count() == 1


def test_changes_are_recorded_against_the_acting_user(
    signed_in: Client, user: User
) -> None:
    signed_in.post(reverse("group_create"), {"name": "Food", "kind": "EXPENSE"})
    group = CategoryGroup.objects.get()
    signed_in.post(
        reverse("group_edit", args=[group.pk]), {"name": "Eat", "kind": "EXPENSE"}
    )
    signed_in.post(reverse("group_delete", args=[group.pk]))

    records = list(CategoryGroup.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "~", "-"]
    assert {r.history_user for r in records} == {user}


def test_admin_shows_groups_with_history(client: Client, superuser: User) -> None:
    client.force_login(superuser)
    group = make_group(superuser, "Food")

    assert (
        client.get(reverse("admin:budget_categorygroup_changelist")).status_code == 200
    )
    history = reverse("admin:budget_categorygroup_history", args=[group.pk])
    assert client.get(history).status_code == 200
