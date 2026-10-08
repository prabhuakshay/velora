from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import Category, CategoryGroup

if TYPE_CHECKING:
    from pathlib import Path

    from django.test import Client
    from pytest_django.fixtures import Settings

    from apps.users.models import User

pytestmark = pytest.mark.django_db

SVG = '<svg class="lucide"></svg>'


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def search(client: Client, query: str, **extra: str) -> str:
    response = client.get(reverse("icon_search"), {"q": query, **extra})
    assert response.status_code == 200
    return response.content.decode()


def test_search_requires_login(client: Client) -> None:
    response = client.get(reverse("icon_search"), {"q": "wallet"})

    assert response.status_code == 302
    assert response["Location"].startswith("/accounts/login/")


def test_search_matches_icon_name(signed_in: Client) -> None:
    body = search(signed_in, "wall")

    assert 'value="wallet"' in body
    assert 'value="house"' not in body


def test_search_matches_keyword(signed_in: Client) -> None:
    assert 'value="wallet"' in search(signed_in, "money")


def test_empty_query_returns_no_results(signed_in: Client) -> None:
    assert 'name="icon"' not in search(signed_in, "  ")


def test_search_results_are_capped(
    signed_in: Client, settings: Settings, tmp_path: Path
) -> None:
    for i in range(60):
        (tmp_path / f"coin-{i}.svg").write_text(SVG)
    (tmp_path / "tags.json").write_text("{}")
    settings.LUCIDE_ICON_DIR = tmp_path

    assert search(signed_in, "coin").count('name="icon"') == 40


def test_search_keeps_selected_icon_checked(signed_in: Client) -> None:
    body = search(signed_in, "money", icon="zebra")

    assert 'value="zebra" checked' in body


def test_form_shows_curated_grid_with_current_icon_selected(
    signed_in: Client, user: User
) -> None:
    group = CategoryGroup.objects.create(owner=user, name="Food")
    category = Category.objects.create(group=group, name="Rent", icon="house")

    body = signed_in.get(reverse("category_edit", args=[category.pk])).content.decode()

    assert 'value="wallet"' in body
    assert 'value="house" checked' in body
    assert 'value="wallet" checked' not in body


def test_new_form_selects_default_icon(signed_in: Client) -> None:
    body = signed_in.get(reverse("category_create")).content.decode()

    assert 'value="tag" checked' in body


def test_form_includes_current_icon_outside_curated_grid(
    signed_in: Client, user: User, settings: Settings, tmp_path: Path
) -> None:
    (tmp_path / "zebra.svg").write_text(SVG)
    (tmp_path / "tag.svg").write_text(SVG)
    settings.LUCIDE_ICON_DIR = tmp_path
    group = CategoryGroup.objects.create(owner=user, name="Food")
    category = Category.objects.create(group=group, name="Pets", icon="zebra")

    body = signed_in.get(reverse("category_edit", args=[category.pk])).content.decode()

    assert 'value="zebra" checked' in body


def test_saving_a_searched_icon_stores_it(signed_in: Client, user: User) -> None:
    group = CategoryGroup.objects.create(owner=user, name="Food")

    signed_in.post(
        reverse("category_create"),
        {"group": group.pk, "name": "Cash", "color": "sky", "icon": "wallet"},
    )

    assert Category.objects.get().icon == "wallet"
