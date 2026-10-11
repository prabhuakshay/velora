from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import KINDS, list_page, list_url

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("url_name", "pk"),
    [
        ("account_list", None),
        ("account_create", None),
        ("account_transactions", 1),
        ("account_edit", 1),
        ("account_hide", 1),
        ("account_unhide", 1),
        ("account_delete", 1),
    ],
)
def test_anonymous_is_redirected_to_login(
    client: Client, kind: str, url_name: str, pk: int | None
) -> None:
    kwargs = {"kind": kind} if pk is None else {"kind": kind, "pk": pk}
    url = reverse(url_name, kwargs=kwargs)

    response = client.post(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_sidebar_links_to_every_account_kind(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    for kind in KINDS:
        assert list_url(kind) in body


@pytest.mark.parametrize("kind", KINDS)
def test_sidebar_marks_the_current_account_kind(signed_in: Client, kind: str) -> None:
    assert f'href="{list_url(kind)}" aria-current="page"' in list_page(signed_in, kind)


@pytest.mark.parametrize("path", ["/accounts/savings/", "/accounts/savings/new/"])
def test_unsupported_kind_is_not_found(signed_in: Client, path: str) -> None:
    assert signed_in.get(path).status_code == 404
