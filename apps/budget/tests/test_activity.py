from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.budget.models import Category

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_category(name: str) -> Category:
    return Category.objects.create(name=name, kind=Category.Kind.EXPENSE, color="cyan")


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def panel(client: Client) -> str:
    return client.get(reverse("category_list")).content.decode()


def test_panel_shows_latest_five_newest_first(signed_in: Client) -> None:
    for i in range(6):
        make_category(f"Cat {i}")

    body = panel(signed_in)

    assert body.index("Created Cat 5") < body.index("Created Cat 1")
    assert "Created Cat 0" not in body
    assert "Show more" in body


def test_wording_for_each_change_type(signed_in: Client) -> None:
    category = make_category("Groceries")

    def edit(**fields: str) -> str:
        for key, value in fields.items():
            setattr(category, key, value)
        category.save()
        return panel(signed_in)

    assert "Renamed Groceries → Food shopping" in edit(name="Food shopping")
    assert "Changed icon of Food shopping" in edit(icon="wallet")
    assert "Changed colour of Food shopping" in edit(color="pink")
    assert "Changed description of Food shopping" in edit(description="x")
    assert "Changed kind of Food shopping" in edit(kind=Category.Kind.INCOME)
    assert "ago" in panel(signed_in)
    category.delete()
    assert "Deleted Food shopping" in panel(signed_in)


def test_show_more_returns_next_five_and_last_page_has_no_button(
    signed_in: Client,
) -> None:
    for i in range(10):
        make_category(f"Cat {i}")

    first = panel(signed_in)
    assert "Created Cat 5" in first
    assert "Created Cat 4" not in first
    assert "offset=5" in first

    url = reverse("category_activity")
    second = signed_in.get(url, {"offset": 5}).content.decode()
    assert "Created Cat 4" in second
    assert "Created Cat 0" in second
    assert "Created Cat 5" not in second
    assert "Show more" not in second


def test_activity_endpoint_requires_login(client: Client) -> None:
    response = client.get(reverse("category_activity"))

    assert response.status_code == 302
    assert "login" in response["Location"]


def test_hidden_and_unhidden_wording(signed_in: Client) -> None:
    category = make_category("Food")
    category.hidden = True
    category.save()
    assert "Hidden Food" in panel(signed_in)

    category.hidden = False
    category.save()
    assert "Unhidden Food" in panel(signed_in)


def test_non_numeric_offset_falls_back_to_first_page(signed_in: Client) -> None:
    make_category("Food")

    response = signed_in.get(reverse("category_activity"), {"offset": "abc"})

    assert response.status_code == 200
    assert "Created Food" in response.content.decode()


def test_panel_query_count_does_not_grow_with_entries(
    signed_in: Client, django_assert_max_num_queries: Any
) -> None:
    for i in range(5):
        category = make_category(f"Cat {i}")
        category.icon = "wallet"
        category.save()

    with django_assert_max_num_queries(10):
        panel(signed_in)
