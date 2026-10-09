from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.forms import CategoryForm
from apps.budget.models import Category

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_category(
    name: str, kind: str = Category.Kind.EXPENSE, **extra: str
) -> Category:
    extra.setdefault("color", "cyan")
    return Category.objects.create(name=name, kind=kind, **extra)


def payload(
    name: str, kind: str = Category.Kind.EXPENSE, **extra: str
) -> dict[str, str]:
    return {"kind": kind, "name": name, "color": "cyan", "icon": "", **extra}


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_create_category_defaults_icon_to_tag(signed_in: Client) -> None:
    assert signed_in.get(reverse("category_create")).status_code == 200

    response = signed_in.post(
        reverse("category_create"), payload("Groceries", color="green")
    )

    assert response["Location"] == reverse("category_list")
    category = Category.objects.get()
    assert (category.kind, category.name, category.icon) == (
        Category.Kind.EXPENSE,
        "Groceries",
        "tag",
    )
    assert (category.color, category.description) == ("green", "")


def test_list_groups_by_kind_expense_first_alphabetically_with_colour(
    signed_in: Client,
) -> None:
    make_category("Snacks", icon="wallet", color="pink")
    make_category("Bread", icon="house", color="cyan")
    make_category("Salary", Category.Kind.INCOME)

    body = signed_in.get(reverse("category_list")).content.decode()

    assert body.index("Bread") < body.index("Snacks") < body.index("Salary")
    assert body.index("Expense") < body.index("Income")
    assert "text-pink-600" in body
    assert "text-cyan-600" in body


def test_duplicate_name_of_same_kind_any_case_shows_error(signed_in: Client) -> None:
    make_category("Groceries")

    response = signed_in.post(reverse("category_create"), payload("gROCERIES"))

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert Category.objects.count() == 1


def test_same_name_of_the_other_kind_is_allowed(signed_in: Client) -> None:
    make_category("Refund")

    response = signed_in.post(
        reverse("category_create"), payload("Refund", Category.Kind.INCOME)
    )

    assert response.status_code == 302
    assert Category.objects.count() == 2


def test_unknown_icon_is_rejected(signed_in: Client) -> None:
    response = signed_in.post(
        reverse("category_create"), payload("Bread", icon="../secret")
    )

    assert response.status_code == 200
    assert b"Unknown icon" in response.content
    assert Category.objects.count() == 0


def test_edit_changes_fields_and_kind(signed_in: Client) -> None:
    category = make_category("Bread")
    url = reverse("category_edit", args=[category.pk])
    assert signed_in.get(url).status_code == 200

    response = signed_in.post(
        url,
        payload(
            "Bread",
            Category.Kind.INCOME,
            icon="house",
            description="Daily",
            color="pink",
        ),
    )

    assert response.status_code == 302
    category.refresh_from_db()
    assert (category.kind, category.icon, category.description, category.color) == (
        Category.Kind.INCOME,
        "house",
        "Daily",
        "pink",
    )


def test_edit_keeping_own_name_is_allowed(signed_in: Client) -> None:
    category = make_category("Bread")

    response = signed_in.post(
        reverse("category_edit", args=[category.pk]), payload("bread")
    )

    assert response.status_code == 302


def test_delete_requires_confirmation_then_deletes(signed_in: Client) -> None:
    category = make_category("Bread")
    url = reverse("category_delete", args=[category.pk])

    assert signed_in.get(url).status_code == 200
    assert Category.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("category_list")
    assert Category.objects.count() == 0


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
    signed_in.post(reverse("category_create"), payload("Bread"))
    category = Category.objects.get()
    signed_in.post(reverse("category_edit", args=[category.pk]), payload("Loaf"))
    signed_in.post(reverse("category_delete", args=[category.pk]))

    records = list(Category.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "~", "-"]
    assert {r.history_user for r in records} == {user}


def test_admin_shows_categories_with_history(client: Client, superuser: User) -> None:
    client.force_login(superuser)
    category = make_category("Bread")

    assert client.get(reverse("admin:budget_category_changelist")).status_code == 200
    history = reverse("admin:budget_category_history", args=[category.pk])
    assert client.get(history).status_code == 200


def test_concurrent_duplicate_category_name_shows_error(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_category("Rent", color="red")
    monkeypatch.setattr(CategoryForm, "clean", lambda self: self.cleaned_data)
    monkeypatch.setattr(Category, "validate_constraints", lambda *_, **__: None)

    response = signed_in.post(reverse("category_create"), payload("rent", color="red"))

    assert response.status_code == 200
    assert "already" in response.content.decode()


def test_category_form_offers_a_swatch_per_colour(signed_in: Client) -> None:
    body = signed_in.get(reverse("category_create")).content.decode()

    assert 'type="radio" name="color" value="cyan"' in body
    assert "bg-cyan-600" in body
    assert '<select name="color"' not in body
