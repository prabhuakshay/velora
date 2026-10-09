from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import Category

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db

HIDE_ACTIONS = ["category_hide", "category_unhide"]


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name="Rent", kind=Category.Kind.EXPENSE, color="red")


def list_page(client: Client, query: str = "") -> str:
    body = client.get(reverse("category_list") + query).content.decode()
    # The activity panel names hidden items too.
    return body.split('id="activity"')[0]


def test_hiding_category_removes_only_it(signed_in: Client, category: Category) -> None:
    Category.objects.create(name="Water", kind=Category.Kind.EXPENSE, color="cyan")

    response = signed_in.post(reverse("category_hide", args=[category.pk]))

    assert response["Location"] == reverse("category_list")
    content = list_page(signed_in)
    assert "Rent" not in content
    assert "Water" in content


def test_show_hidden_reveals_dimmed_items_with_unhide(
    signed_in: Client, category: Category
) -> None:
    signed_in.post(reverse("category_hide", args=[category.pk]))

    content = list_page(signed_in, "?show_hidden=1")

    assert "Rent" in content
    assert "opacity-50" in content
    assert reverse("category_unhide", args=[category.pk]) in content


def test_unhide_restores_category(signed_in: Client, category: Category) -> None:
    signed_in.post(reverse("category_hide", args=[category.pk]))
    signed_in.post(reverse("category_unhide", args=[category.pk]))

    assert "Rent" in list_page(signed_in)


@pytest.mark.parametrize("name", HIDE_ACTIONS)
def test_hide_actions_reject_get(
    signed_in: Client, category: Category, name: str
) -> None:
    assert signed_in.get(reverse(name, args=[category.pk])).status_code == 405


def test_edit_form_can_set_hidden(signed_in: Client, category: Category) -> None:
    signed_in.post(
        reverse("category_edit", args=[category.pk]),
        {"kind": "EXPENSE", "name": "Rent", "color": "red", "icon": "", "hidden": "on"},
    )

    assert "Rent" not in list_page(signed_in)


def test_hiding_is_recorded_in_history(signed_in: Client, category: Category) -> None:
    signed_in.post(reverse("category_hide", args=[category.pk]))

    assert category.history.first().hidden


def test_show_hidden_only_on_for_exactly_one(
    signed_in: Client, category: Category
) -> None:
    category.hidden = True
    category.save()

    assert "Rent" not in list_page(signed_in, "?show_hidden=0")


@pytest.mark.parametrize("name", HIDE_ACTIONS)
def test_hide_actions_keep_show_hidden(
    signed_in: Client, category: Category, name: str
) -> None:
    response = signed_in.post(reverse(name, args=[category.pk]) + "?show_hidden=1")

    assert response["Location"] == reverse("category_list") + "?show_hidden=1"


def test_list_forms_carry_show_hidden(signed_in: Client, category: Category) -> None:
    content = list_page(signed_in, "?show_hidden=1")

    assert reverse("category_hide", args=[category.pk]) + "?show_hidden=1" in content
