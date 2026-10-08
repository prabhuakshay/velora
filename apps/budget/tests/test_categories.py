from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import Category, CategoryGroup

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_group(owner: User, name: str) -> CategoryGroup:
    return CategoryGroup.objects.create(
        owner=owner, name=name, kind=CategoryGroup.Kind.EXPENSE
    )


def make_category(group: CategoryGroup, name: str, **extra: str) -> Category:
    return Category.objects.create(group=group, name=name, **extra)


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_create_category_defaults_icon_to_tag(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")
    assert signed_in.get(reverse("category_create")).status_code == 200

    response = signed_in.post(
        reverse("category_create"),
        {"group": group.pk, "name": "Groceries", "color": "emerald", "icon": ""},
    )

    assert response["Location"] == reverse("category_list")
    category = Category.objects.get()
    assert (category.group, category.name, category.icon, category.color) == (
        group,
        "Groceries",
        "tag",
        "emerald",
    )
    assert category.description == ""


def test_list_shows_categories_alphabetically_with_icon_in_colour(
    signed_in: Client, user: User
) -> None:
    group = make_group(user, "Food")
    make_category(group, "Snacks", icon="wallet", color="rose")
    make_category(group, "Bread", icon="house", color="sky")

    body = signed_in.get(reverse("category_list")).content.decode()

    assert body.index("Bread") < body.index("Snacks")
    assert "text-rose-600" in body
    assert "text-sky-600" in body


def payload(group: CategoryGroup, name: str, **extra: str) -> dict[str, str | int]:
    return {"group": group.pk, "name": name, "color": "sky", "icon": "", **extra}


def test_duplicate_name_in_same_group_any_case_shows_error(
    signed_in: Client, user: User
) -> None:
    group = make_group(user, "Food")
    make_category(group, "Groceries", color="sky")

    response = signed_in.post(reverse("category_create"), payload(group, "gROCERIES"))

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert Category.objects.count() == 1


def test_same_name_in_another_group_is_allowed(signed_in: Client, user: User) -> None:
    make_category(make_group(user, "Food"), "Misc", color="sky")
    travel = make_group(user, "Travel")

    response = signed_in.post(reverse("category_create"), payload(travel, "Misc"))

    assert response.status_code == 302
    assert Category.objects.count() == 2


def test_unknown_icon_is_rejected(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")

    response = signed_in.post(
        reverse("category_create"), payload(group, "Bread", icon="../secret")
    )

    assert response.status_code == 200
    assert b"Unknown icon" in response.content
    assert Category.objects.count() == 0


def test_edit_changes_fields_and_moves_group(signed_in: Client, user: User) -> None:
    food = make_group(user, "Food")
    home = make_group(user, "Home")
    category = make_category(food, "Bread", color="sky")
    url = reverse("category_edit", args=[category.pk])
    assert signed_in.get(url).status_code == 200

    response = signed_in.post(
        url, payload(home, "Bread", icon="house", description="Daily", color="rose")
    )

    assert response.status_code == 302
    category.refresh_from_db()
    assert (category.group, category.icon, category.description, category.color) == (
        home,
        "house",
        "Daily",
        "rose",
    )


def test_edit_keeping_own_name_is_allowed(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")
    category = make_category(group, "Bread", color="sky")

    response = signed_in.post(
        reverse("category_edit", args=[category.pk]), payload(group, "bread")
    )

    assert response.status_code == 302


def test_group_dropdown_excludes_other_users_groups(
    signed_in: Client, user: User, other_user: User
) -> None:
    make_group(user, "Mine")
    theirs = make_group(other_user, "Theirs")

    response = signed_in.post(reverse("category_create"), payload(theirs, "Bread"))

    assert response.status_code == 200
    assert b"Theirs" not in response.content
    assert Category.objects.count() == 0


def test_delete_requires_confirmation_then_deletes(
    signed_in: Client, user: User
) -> None:
    category = make_category(make_group(user, "Food"), "Bread", color="sky")
    url = reverse("category_delete", args=[category.pk])

    assert signed_in.get(url).status_code == 200
    assert Category.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("category_list")
    assert Category.objects.count() == 0


def test_delete_of_group_with_categories_is_blocked_with_count(
    signed_in: Client, user: User
) -> None:
    group = make_group(user, "Food")
    make_category(group, "Bread", color="sky")
    make_category(group, "Milk", color="sky")
    url = reverse("group_delete", args=[group.pk])

    page = signed_in.get(url)
    refused = signed_in.post(url)

    assert b"2 categories" in page.content
    assert b"<button" not in page.content
    assert refused.status_code == 409
    assert CategoryGroup.objects.count() == 1
    assert Category.objects.count() == 2


@pytest.mark.parametrize("url_name", ["category_edit", "category_delete"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_other_users_category_is_not_found(
    signed_in: Client, other_user: User, url_name: str, method: str
) -> None:
    category = make_category(make_group(other_user, "Food"), "Bread", color="sky")

    response = getattr(signed_in, method)(reverse(url_name, args=[category.pk]))

    assert response.status_code == 404
    assert Category.objects.count() == 1


@pytest.mark.parametrize(
    ("url_name", "args"),
    [("category_create", []), ("category_edit", [1]), ("category_delete", [1])],
)
def test_anonymous_is_redirected_to_login(
    client: Client, url_name: str, args: list[int]
) -> None:
    url = reverse(url_name, args=args)

    response = client.get(url)

    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_every_change_is_recorded(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")
    signed_in.post(reverse("category_create"), payload(group, "Bread"))
    category = Category.objects.get()
    signed_in.post(reverse("category_edit", args=[category.pk]), payload(group, "Loaf"))
    signed_in.post(reverse("category_delete", args=[category.pk]))

    records = list(Category.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "~", "-"]
    assert {r.history_user for r in records} == {user}


def test_admin_shows_categories_with_history(client: Client, superuser: User) -> None:
    client.force_login(superuser)
    category = make_category(make_group(superuser, "Food"), "Bread", color="sky")

    assert client.get(reverse("admin:budget_category_changelist")).status_code == 200
    history = reverse("admin:budget_category_history", args=[category.pk])
    assert client.get(history).status_code == 200
