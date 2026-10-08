from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.forms import PartyForm
from apps.budget.models import Party

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_party(owner: User, name: str, **fields: object) -> Party:
    return Party.objects.create(owner=owner, name=name, **fields)


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def list_page(client: Client, query: str = "") -> str:
    return client.get(reverse("party_list") + query).content.decode()


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("party_list", []),
        ("party_create", []),
        ("party_edit", [1]),
        ("party_delete", [1]),
        ("party_merge", [1]),
        ("party_hide", [1]),
        ("party_unhide", [1]),
    ],
)
def test_anonymous_is_redirected_to_login(
    client: Client, url_name: str, args: list[int]
) -> None:
    url = reverse(url_name, args=args)

    response = client.post(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_index_links_to_parties(signed_in: Client) -> None:
    response = signed_in.get(reverse("index"))

    assert reverse("party_list").encode() in response.content


def test_create_party_with_notes(signed_in: Client, user: User) -> None:
    assert signed_in.get(reverse("party_create")).status_code == 200

    response = signed_in.post(
        reverse("party_create"), {"name": "Walmart", "notes": "Card ending 1234"}
    )

    assert response["Location"] == reverse("party_list")
    party = Party.objects.get()
    assert (party.owner, party.name, party.notes, party.hidden) == (
        user,
        "Walmart",
        "Card ending 1234",
        False,
    )


def test_notes_are_optional(signed_in: Client) -> None:
    response = signed_in.post(reverse("party_create"), {"name": "Walmart"})

    assert response.status_code == 302
    assert Party.objects.get().notes == ""


def test_list_sorted_by_name_ignoring_case(signed_in: Client, user: User) -> None:
    for name in ["walmart", "Acme", "employer", "Bakery"]:
        make_party(user, name)

    body = list_page(signed_in)

    positions = [body.index(n) for n in ["Acme", "Bakery", "employer", "walmart"]]
    assert positions == sorted(positions)


def test_list_shows_only_own_parties(signed_in: Client, other_user: User) -> None:
    make_party(other_user, "Secret")

    assert "Secret" not in list_page(signed_in)


def test_create_duplicate_name_in_any_case_shows_error(
    signed_in: Client, user: User
) -> None:
    make_party(user, "Walmart")

    response = signed_in.post(reverse("party_create"), {"name": "walmart"})

    assert response.status_code == 200
    assert b"already exists" in response.content
    assert Party.objects.count() == 1


def test_different_users_may_share_a_name(signed_in: Client, other_user: User) -> None:
    make_party(other_user, "Walmart")

    response = signed_in.post(reverse("party_create"), {"name": "Walmart"})

    assert response.status_code == 302
    assert Party.objects.count() == 2


def test_edit_renames_and_updates_notes(signed_in: Client, user: User) -> None:
    party = make_party(user, "Walmrt", notes="old")

    response = signed_in.post(
        reverse("party_edit", args=[party.pk]), {"name": "Walmart", "notes": "new"}
    )

    assert response["Location"] == reverse("party_list")
    party.refresh_from_db()
    assert (party.name, party.notes) == ("Walmart", "new")


def test_edit_form_renders_current_values(signed_in: Client, user: User) -> None:
    party = make_party(user, "Walmart", notes="Card ending 1234")

    response = signed_in.get(reverse("party_edit", args=[party.pk]))

    assert b"Walmart" in response.content
    assert b"Card ending 1234" in response.content


def test_edit_keeping_own_name_in_other_case_is_allowed(
    signed_in: Client, user: User
) -> None:
    party = make_party(user, "Walmart")

    response = signed_in.post(
        reverse("party_edit", args=[party.pk]), {"name": "WALMART"}
    )

    assert response.status_code == 302


def test_edit_to_existing_name_shows_error(signed_in: Client, user: User) -> None:
    make_party(user, "Walmart")
    party = make_party(user, "Acme")

    response = signed_in.post(
        reverse("party_edit", args=[party.pk]), {"name": "walmart"}
    )

    assert b"already exists" in response.content
    party.refresh_from_db()
    assert party.name == "Acme"


def test_hide_removes_party_from_default_list(signed_in: Client, user: User) -> None:
    party = make_party(user, "Walmart")

    response = signed_in.post(reverse("party_hide", args=[party.pk]))

    assert response["Location"] == reverse("party_list")
    assert "Walmart" not in list_page(signed_in)


def test_show_hidden_reveals_dimmed_party_with_unhide(
    signed_in: Client, user: User
) -> None:
    party = make_party(user, "Walmart", hidden=True)

    content = list_page(signed_in, "?show_hidden=1")

    assert "Walmart" in content
    assert "opacity-50" in content
    assert reverse("party_unhide", args=[party.pk]) + "?show_hidden=1" in content


def test_unhide_restores_party(signed_in: Client, user: User) -> None:
    party = make_party(user, "Walmart", hidden=True)

    response = signed_in.post(
        reverse("party_unhide", args=[party.pk]) + "?show_hidden=1"
    )

    assert response["Location"] == reverse("party_list") + "?show_hidden=1"
    assert "Walmart" in list_page(signed_in)


def test_edit_form_can_set_hidden(signed_in: Client, user: User) -> None:
    party = make_party(user, "Walmart")

    signed_in.post(
        reverse("party_edit", args=[party.pk]), {"name": "Walmart", "hidden": "on"}
    )

    assert "Walmart" not in list_page(signed_in)


@pytest.mark.parametrize("name", ["party_hide", "party_unhide"])
def test_hide_actions_reject_get(signed_in: Client, user: User, name: str) -> None:
    party = make_party(user, "Walmart")

    assert signed_in.get(reverse(name, args=[party.pk])).status_code == 405


def test_delete_requires_confirmation_then_deletes(
    signed_in: Client, user: User
) -> None:
    party = make_party(user, "Walmart")
    url = reverse("party_delete", args=[party.pk])

    assert signed_in.get(url).status_code == 200
    assert Party.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == reverse("party_list")
    assert not Party.objects.exists()


@pytest.mark.parametrize(
    "url_name", ["party_edit", "party_delete", "party_merge", "party_hide"]
)
def test_other_users_party_is_not_found(
    signed_in: Client, other_user: User, url_name: str
) -> None:
    party = make_party(other_user, "Walmart")

    response = signed_in.post(reverse(url_name, args=[party.pk]), {"name": "Mine"})

    assert response.status_code == 404
    party.refresh_from_db()
    assert (party.name, party.hidden) == ("Walmart", False)


def test_changes_are_recorded_against_the_acting_user(
    signed_in: Client, user: User
) -> None:
    signed_in.post(reverse("party_create"), {"name": "Walmart"})
    party = Party.objects.get()
    signed_in.post(reverse("party_edit", args=[party.pk]), {"name": "Acme"})
    signed_in.post(reverse("party_hide", args=[party.pk]))
    signed_in.post(reverse("party_delete", args=[party.pk]))

    records = list(Party.history.order_by("history_date"))

    assert [r.history_type for r in records] == ["+", "~", "~", "-"]
    assert {r.history_user for r in records} == {user}


def test_admin_shows_parties_with_history(client: Client, superuser: User) -> None:
    client.force_login(superuser)
    party = make_party(superuser, "Walmart")

    assert client.get(reverse("admin:budget_party_changelist")).status_code == 200
    history = reverse("admin:budget_party_history", args=[party.pk])
    assert client.get(history).status_code == 200


def test_deleting_a_user_removes_their_parties(user: User, other_user: User) -> None:
    make_party(user, "Walmart")
    make_party(other_user, "Acme")

    user.delete()

    assert [p.name for p in Party.objects.all()] == ["Acme"]


def test_concurrent_duplicate_party_name_shows_error(
    signed_in: Client, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_party(user, "Walmart")
    # Simulates the race: validation passed before the other request committed.
    monkeypatch.setattr(PartyForm, "clean_name", lambda self: "Walmart")

    response = signed_in.post(reverse("party_create"), {"name": "walmart"})

    assert response.status_code == 200
    assert "already" in response.content.decode()
