from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import Category, CategoryGroup

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db

HIDE_ACTIONS = ["group_hide", "group_unhide", "category_hide", "category_unhide"]


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.fixture
def group(user: User) -> CategoryGroup:
    return CategoryGroup.objects.create(
        owner=user, name="Housing", kind=CategoryGroup.Kind.EXPENSE
    )


@pytest.fixture
def category(group: CategoryGroup) -> Category:
    return Category.objects.create(group=group, name="Rent", color="red")


def list_page(client: Client, query: str = "") -> str:
    body = client.get(reverse("category_list") + query).content.decode()
    # The activity panel names hidden items too.
    return body.split('id="activity"')[0]


def test_hiding_group_removes_it_and_its_categories(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    response = signed_in.post(reverse("group_hide", args=[group.pk]))

    assert response["Location"] == reverse("category_list")
    content = list_page(signed_in)
    assert "Housing" not in content
    assert "Rent" not in content


def test_hiding_category_removes_only_it(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    Category.objects.create(group=group, name="Water", color="cyan")

    signed_in.post(reverse("category_hide", args=[category.pk]))

    content = list_page(signed_in)
    assert "Rent" not in content
    assert "Water" in content
    assert "Housing" in content


def test_show_hidden_reveals_dimmed_items_with_unhide(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    signed_in.post(reverse("group_hide", args=[group.pk]))

    content = list_page(signed_in, "?show_hidden=1")

    assert "Housing" in content
    assert "Rent" in content
    assert "opacity-50" in content
    assert reverse("group_unhide", args=[group.pk]) in content


def test_unhide_restores_group_and_category(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    signed_in.post(reverse("category_hide", args=[category.pk]))
    signed_in.post(reverse("category_unhide", args=[category.pk]))
    signed_in.post(reverse("group_hide", args=[group.pk]))
    signed_in.post(reverse("group_unhide", args=[group.pk]))

    content = list_page(signed_in)
    assert "Housing" in content
    assert "Rent" in content


def test_individually_hidden_category_stays_hidden_after_group_roundtrip(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    signed_in.post(reverse("category_hide", args=[category.pk]))
    signed_in.post(reverse("group_hide", args=[group.pk]))
    signed_in.post(reverse("group_unhide", args=[group.pk]))

    content = list_page(signed_in)
    assert "Housing" in content
    assert "Rent" not in content


@pytest.mark.parametrize("name", HIDE_ACTIONS)
def test_hide_actions_reject_get(
    signed_in: Client, group: CategoryGroup, category: Category, name: str
) -> None:
    pk = group.pk if name.startswith("group") else category.pk
    assert signed_in.get(reverse(name, args=[pk])).status_code == 405


@pytest.mark.parametrize("name", HIDE_ACTIONS)
def test_hide_actions_404_for_other_users_objects(
    client: Client,
    other_user: User,
    group: CategoryGroup,
    category: Category,
    name: str,
) -> None:
    client.force_login(other_user)
    pk = group.pk if name.startswith("group") else category.pk

    assert client.post(reverse(name, args=[pk])).status_code == 404


def test_edit_forms_can_set_hidden(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    signed_in.post(
        reverse("group_edit", args=[group.pk]),
        {"name": "Housing", "kind": "EXPENSE", "hidden": "on"},
    )
    signed_in.post(
        reverse("category_edit", args=[category.pk]),
        {"group": group.pk, "name": "Rent", "color": "red", "icon": "", "hidden": "on"},
    )

    content = list_page(signed_in)
    assert "Housing" not in content
    assert "Rent" not in content


def test_hiding_is_recorded_in_history(
    signed_in: Client, group: CategoryGroup, category: Category
) -> None:
    signed_in.post(reverse("group_hide", args=[group.pk]))
    signed_in.post(reverse("category_hide", args=[category.pk]))

    assert group.history.first().hidden
    assert category.history.first().hidden
    assert group.history.count() == 2


def test_show_hidden_only_on_for_exactly_one(
    signed_in: Client, group: CategoryGroup
) -> None:
    group.hidden = True
    group.save()

    assert "Housing" not in list_page(signed_in, "?show_hidden=0")


@pytest.mark.parametrize("name", HIDE_ACTIONS)
def test_hide_actions_keep_show_hidden(
    signed_in: Client, group: CategoryGroup, category: Category, name: str
) -> None:
    pk = group.pk if name.startswith("group") else category.pk

    response = signed_in.post(reverse(name, args=[pk]) + "?show_hidden=1")

    assert response["Location"] == reverse("category_list") + "?show_hidden=1"


def test_list_forms_carry_show_hidden(signed_in: Client, group: CategoryGroup) -> None:
    content = list_page(signed_in, "?show_hidden=1")

    assert reverse("group_hide", args=[group.pk]) + "?show_hidden=1" in content
