from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import Party

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_party(owner: User, name: str) -> Party:
    return Party.objects.create(owner=owner, name=name)


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_merge_removes_source_and_keeps_target(signed_in: Client, user: User) -> None:
    source = make_party(user, "Walmrt")
    target = make_party(user, "Walmart")
    url = reverse("party_merge", args=[source.pk])

    page = signed_in.get(url)
    assert page.status_code == 200
    assert b"Walmart" in page.content

    response = signed_in.post(url, {"target": target.pk})

    assert response["Location"] == reverse("party_list")
    assert list(Party.objects.all()) == [target]


def test_merge_into_itself_is_refused(signed_in: Client, user: User) -> None:
    source = make_party(user, "Walmart")

    response = signed_in.post(
        reverse("party_merge", args=[source.pk]), {"target": source.pk}
    )

    assert response.status_code == 200
    assert Party.objects.count() == 1


def test_merge_into_other_users_party_is_refused(
    signed_in: Client, user: User, other_user: User
) -> None:
    source = make_party(user, "Walmart")
    foreign = make_party(other_user, "Acme")

    response = signed_in.post(
        reverse("party_merge", args=[source.pk]), {"target": foreign.pk}
    )

    assert response.status_code == 200
    assert Party.objects.count() == 2


def test_merge_page_does_not_offer_source_or_foreign_parties(
    signed_in: Client, user: User, other_user: User
) -> None:
    source = make_party(user, "Walmrt")
    make_party(user, "Walmart")
    make_party(other_user, "Secret")

    body = signed_in.get(reverse("party_merge", args=[source.pk])).content.decode()

    assert f'value="{source.pk}"' not in body
    assert "Secret" not in body
