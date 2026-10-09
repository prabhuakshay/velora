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


def accounts_group_tag(body: str) -> str:
    before_summary = body[: body.index("Accounts\n")]
    return before_summary.rsplit("<details", 1)[1].split(">", maxsplit=1)[0]


def test_sidebar_links_to_accounts_in_a_closed_group(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "open" not in accounts_group_tag(body)
    for kind in KINDS:
        assert list_url(kind) in body


@pytest.mark.parametrize("kind", KINDS)
def test_sidebar_accounts_group_is_open_on_its_pages(
    signed_in: Client, kind: str
) -> None:
    assert "open" in accounts_group_tag(list_page(signed_in, kind))


@pytest.mark.parametrize("path", ["/accounts/savings/", "/accounts/savings/new/"])
def test_unsupported_kind_is_not_found(signed_in: Client, path: str) -> None:
    assert signed_in.get(path).status_code == 404
