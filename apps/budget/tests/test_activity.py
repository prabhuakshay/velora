from typing import TYPE_CHECKING, Any

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


def make_category(group: CategoryGroup, name: str) -> Category:
    return Category.objects.create(group=group, name=name, color="cyan")


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def panel(client: Client) -> str:
    return client.get(reverse("category_list")).content.decode()


def test_panel_shows_latest_five_newest_first(signed_in: Client, user: User) -> None:
    group = make_group(user, "Group A")
    for i in range(5):
        make_category(group, f"Cat {i}")

    body = panel(signed_in)

    assert body.index("Created Cat 4") < body.index("Created Cat 0")
    assert "Created Group A" not in body
    assert "Show more" in body


def test_wording_for_each_change_type(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")
    other = make_group(user, "Home")
    category = make_category(group, "Groceries")

    def edit(**fields: str | CategoryGroup) -> str:
        for key, value in fields.items():
            setattr(category, key, value)
        category.save()
        return panel(signed_in)

    assert "Renamed Groceries → Food shopping" in edit(name="Food shopping")
    assert "Changed icon of Food shopping" in edit(icon="wallet")
    assert "Changed colour of Food shopping" in edit(color="pink")
    assert "Changed description of Food shopping" in edit(description="x")
    assert "Moved Food shopping to Home" in edit(group=other)
    assert "ago" in panel(signed_in)
    category.delete()
    assert "Deleted Food shopping" in panel(signed_in)


def test_group_changes_use_the_same_wording(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")
    group.name = "Eating"
    group.save()

    assert "Renamed Food → Eating" in panel(signed_in)


def test_entries_for_deleted_groups_still_appear(signed_in: Client, user: User) -> None:
    make_group(user, "Gone").delete()

    assert "Deleted Gone" in panel(signed_in)


def test_show_more_returns_next_five_and_last_page_has_no_button(
    signed_in: Client, user: User
) -> None:
    group = make_group(user, "G")
    for i in range(10):
        make_category(group, f"Cat {i}")
    # 11 entries in total: 10 categories plus the group.

    first = panel(signed_in)
    assert "Created Cat 5" in first
    assert "Created Cat 4" not in first
    assert "offset=5" in first

    url = reverse("category_activity")
    second = signed_in.get(url, {"offset": 5}).content.decode()
    assert "Created Cat 4" in second
    assert "Created Cat 0" in second
    assert "Created Cat 5" not in second
    assert "offset=10" in second

    last = signed_in.get(url, {"offset": 10}).content.decode()
    assert "Created G" in last
    assert "Show more" not in last


def test_only_own_activity_appears(
    signed_in: Client, user: User, other_user: User
) -> None:
    make_category(make_group(other_user, "Secret"), "Private thing")

    body = panel(signed_in)

    assert "Secret" not in body
    assert "Private thing" not in body


def test_activity_endpoint_requires_login(client: Client) -> None:
    response = client.get(reverse("category_activity"))

    assert response.status_code == 302
    assert "login" in response["Location"]


def test_hidden_and_unhidden_wording(signed_in: Client, user: User) -> None:
    group = make_group(user, "Food")
    group.hidden = True
    group.save()
    assert "Hidden Food" in panel(signed_in)

    group.hidden = False
    group.save()
    assert "Unhidden Food" in panel(signed_in)


def test_non_numeric_offset_falls_back_to_first_page(
    signed_in: Client, user: User
) -> None:
    make_group(user, "Food")

    response = signed_in.get(reverse("category_activity"), {"offset": "abc"})

    assert response.status_code == 200
    assert "Created Food" in response.content.decode()


def test_moved_entry_uses_group_name_at_that_time(
    signed_in: Client, user: User
) -> None:
    category = make_category(make_group(user, "Food"), "Groceries")
    home = make_group(user, "Home")
    category.group = home
    category.save()
    home.name = "House"
    home.save()

    assert "Moved Groceries to Home" in panel(signed_in)


def test_panel_query_count_does_not_grow_with_entries(
    signed_in: Client, user: User, django_assert_max_num_queries: Any
) -> None:
    group = make_group(user, "Food")
    other = make_group(user, "Home")
    for i in range(5):
        category = make_category(group, f"Cat {i}")
        category.group = other
        category.save()

    with django_assert_max_num_queries(12):
        panel(signed_in)
