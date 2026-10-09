from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, edit_account, list_page
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_net_worth import home_page
from apps.accounts.tests.test_opening_balance import (
    KINDS_WITH_BALANCE,
    KINDS_WITHOUT_BALANCE,
)

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account


pytestmark = pytest.mark.django_db

CHECKED_BOX = b'name="include_in_net_worth" id="id_include_in_net_worth" checked'


def exclude(client: Client, account: Account) -> None:
    edit_account(client, account, include_in_net_worth=False)


@pytest.mark.parametrize("kind", KINDS_WITH_BALANCE)
def test_balance_form_includes_in_net_worth_by_default(
    signed_in: Client, kind: str
) -> None:
    body = signed_in.get(reverse("account_create", kwargs={"kind": kind})).content

    assert CHECKED_BOX in body


@pytest.mark.parametrize("kind", KINDS_WITHOUT_BALANCE)
def test_form_without_balance_has_no_include_setting(
    signed_in: Client, kind: str
) -> None:
    body = signed_in.get(reverse("account_create", kwargs={"kind": kind})).content

    assert b"include_in_net_worth" not in body


def test_excluded_accounts_drop_out_of_net_worth(signed_in: Client) -> None:
    opening("Bank", "asset", "1000.00")
    car = opening("Car", "asset", "5000.00")
    opening("Card", "liability", "200.00")
    covered_by_parent = opening("Parent loan", "liability", "300.00")
    exclude(signed_in, car)
    exclude(signed_in, covered_by_parent)

    page = home_page(signed_in)

    assert "Assets ₹1,000.00" in page
    assert "Liabilities ₹200.00" in page
    assert "Net Worth ₹800.00" in page


@pytest.mark.parametrize("kind", KINDS_WITH_BALANCE)
def test_list_marks_excluded_accounts(signed_in: Client, kind: str) -> None:
    exclude(signed_in, opening("Excluded", kind, "10.00"))
    opening("Included", kind, "10.00")

    page = list_page(signed_in, kind)

    assert page.count("Excluded from Net Worth") == 1
    assert page.index("Excluded from Net Worth") < page.index("Included")


def test_hiding_and_unhiding_keep_the_include_setting(signed_in: Client) -> None:
    opening("Bank", "asset", "1000.00")
    car = opening("Car", "asset", "5000.00")
    exclude(signed_in, car)

    signed_in.post(account_url("account_hide", car))
    assert "Net Worth ₹1,000.00" in home_page(signed_in)

    signed_in.post(account_url("account_unhide", car))
    assert "Net Worth ₹1,000.00" in home_page(signed_in)


@pytest.mark.parametrize(
    ("exclude_source", "net_worth"),
    [(True, "Net Worth ₹1,050.00"), (False, "Net Worth ₹0.00")],
)
def test_merge_keeps_the_targets_include_setting(
    signed_in: Client, *, exclude_source: bool, net_worth: str
) -> None:
    source = opening("Old bank", "asset", "50.00")
    target = opening("Bank", "asset", "1000.00")
    exclude(signed_in, source if exclude_source else target)

    signed_in.post(account_url("account_merge", source), {"target": target.pk})

    assert net_worth in home_page(signed_in)
