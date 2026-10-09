from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.classification.models import Tag

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def list_page(client: Client, query: str = "") -> str:
    return client.get(reverse("tag_list") + query).content.decode()


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("tag_list", []),
        ("tag_create", []),
        ("tag_edit", [1]),
        ("tag_delete", [1]),
        ("tag_hide", [1]),
        ("tag_unhide", [1]),
        ("tag_merge", [1]),
    ],
)
def test_anonymous_is_redirected_to_login(
    client: Client, url_name: str, args: list[int]
) -> None:
    url = reverse(url_name, args=args)

    response = client.post(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_sidebar_links_to_tags(signed_in: Client) -> None:
    response = signed_in.get(reverse("index"))

    assert reverse("tag_list").encode() in response.content


def test_create_tag_with_color(signed_in: Client) -> None:
    assert b'value="slate" checked' in signed_in.get(reverse("tag_create")).content

    response = signed_in.post(
        reverse("tag_create"), {"name": "goa-trip-2026", "color": "green"}
    )

    assert response["Location"] == reverse("tag_list")
    tag = Tag.objects.get()
    assert (tag.name, tag.color, tag.hidden) == ("goa-trip-2026", "green", False)
    assert "bg-green-600" in list_page(signed_in)


def test_unknown_color_is_rejected(signed_in: Client) -> None:
    response = signed_in.post(reverse("tag_create"), {"name": "x", "color": "black"})

    assert response.status_code == 200
    assert not Tag.objects.exists()


def test_create_duplicate_name_in_any_case_shows_error(signed_in: Client) -> None:
    Tag.objects.create(name="Reimbursable")

    response = signed_in.post(
        reverse("tag_create"), {"name": "reimbursable", "color": "red"}
    )

    assert b"already exists" in response.content
    assert Tag.objects.count() == 1


def test_edit_changes_name_and_color(signed_in: Client) -> None:
    tag = Tag.objects.create(name="Reimbursible")

    response = signed_in.post(
        reverse("tag_edit", args=[tag.pk]), {"name": "Reimbursable", "color": "blue"}
    )

    assert response["Location"] == reverse("tag_list")
    tag.refresh_from_db()
    assert (tag.name, tag.color) == ("Reimbursable", "blue")


def test_hide_and_unhide(signed_in: Client) -> None:
    tag = Tag.objects.create(name="Reimbursable")

    signed_in.post(reverse("tag_hide", args=[tag.pk]))

    assert "Reimbursable" not in list_page(signed_in)
    assert reverse("tag_unhide", args=[tag.pk]) in list_page(
        signed_in, "?show_hidden=1"
    )

    signed_in.post(reverse("tag_unhide", args=[tag.pk]))

    assert "Reimbursable" in list_page(signed_in)


@pytest.mark.parametrize("name", ["tag_hide", "tag_unhide"])
def test_hide_actions_reject_get(signed_in: Client, name: str) -> None:
    tag = Tag.objects.create(name="Reimbursable")

    assert signed_in.get(reverse(name, args=[tag.pk])).status_code == 405


def test_delete_requires_confirmation_then_deletes(signed_in: Client) -> None:
    tag = Tag.objects.create(name="Reimbursable")
    url = reverse("tag_delete", args=[tag.pk])

    assert b"Reimbursable" in signed_in.get(url).content
    assert Tag.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("tag_list")
    assert not Tag.objects.exists()


def test_changes_are_recorded_against_the_acting_user(
    signed_in: Client, user: User
) -> None:
    signed_in.post(reverse("tag_create"), {"name": "Trip", "color": "red"})
    tag = Tag.objects.get()
    signed_in.post(reverse("tag_delete", args=[tag.pk]))

    records = list(Tag.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "-"]
    assert {r.history_user for r in records} == {user}


def test_admin_shows_tags_with_history(client: Client, superuser: User) -> None:
    client.force_login(superuser)
    tag = Tag.objects.create(name="Trip")

    assert client.get(reverse("admin:classification_tag_changelist")).status_code == 200
    history = reverse("admin:classification_tag_history", args=[tag.pk])
    assert client.get(history).status_code == 200
