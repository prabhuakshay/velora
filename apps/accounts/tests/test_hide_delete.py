from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import (
    KINDS,
    account_url,
    list_page,
    list_url,
    make_account,
)

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def shown_part(client: Client, kind: str) -> str:
    """The list above its folded-away hidden Accounts."""
    return list_page(client, kind).split("data-filter-folded")[0]


@pytest.mark.parametrize("kind", KINDS)
def test_hide_folds_the_account_away_and_its_page_offers_unhide(
    signed_in: Client, kind: str
) -> None:
    account = make_account(name="Old card", kind=kind)

    response = signed_in.post(account_url("account_hide", account))

    assert response["Location"] == account_url("account_transactions", account)
    page = signed_in.get(response["Location"]).content.decode()
    assert account_url("account_unhide", account) in page
    assert "Old card" not in shown_part(signed_in, kind)
    assert "Old card" in list_page(signed_in, kind)


@pytest.mark.parametrize("kind", KINDS)
def test_unhide_returns_the_account_to_the_list(signed_in: Client, kind: str) -> None:
    account = make_account(name="Old card", kind=kind, hidden=True)

    response = signed_in.post(account_url("account_unhide", account))

    assert response["Location"] == account_url("account_transactions", account)
    assert "Old card" in shown_part(signed_in, kind)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("url_name", ["account_hide", "account_unhide"])
def test_hide_actions_reject_get(signed_in: Client, kind: str, url_name: str) -> None:
    account = make_account(name="Old card", kind=kind)

    assert signed_in.get(account_url(url_name, account)).status_code == 405


@pytest.mark.parametrize("kind", KINDS)
def test_delete_requires_confirmation_then_deletes(
    signed_in: Client, kind: str
) -> None:
    account = make_account(name="Old card", kind=kind)
    url = account_url("account_delete", account)

    confirmation = signed_in.get(url).content.decode()
    assert "Old card" in confirmation
    assert list_url(kind) in confirmation
    assert Account.objects.count() == 1

    response = signed_in.post(url)

    assert response["Location"] == list_url(kind)
    assert not Account.objects.exists()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "url_name", ["account_hide", "account_unhide", "account_delete"]
)
def test_action_url_with_another_kind_is_not_found(
    signed_in: Client, kind: str, url_name: str
) -> None:
    other = next(k for k in KINDS if k != kind)
    account = make_account(name="Old card", kind=other)

    url = reverse(url_name, kwargs={"kind": kind, "pk": account.pk})

    assert signed_in.post(url).status_code == 404
    assert Account.objects.filter(hidden=False).count() == 1
