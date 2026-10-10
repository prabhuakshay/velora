from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def edit_data(account: Account, threshold: str) -> dict[str, str]:
    return {
        "name": account.name,
        "opening_balance": "0",
        "opening_balance_date": "2026-01-01",
        "include_in_net_worth": "on",
        "low_balance_threshold": threshold,
    }


def test_an_account_saves_its_low_balance_threshold(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")

    response = signed_in.post(
        account_url("account_edit", bank), edit_data(bank, "5000")
    )

    assert response.status_code == 302
    bank.refresh_from_db()
    assert bank.low_balance_threshold == Decimal(5000)


def test_a_blank_threshold_saves_as_zero(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    bank.low_balance_threshold = Decimal(5000)
    bank.save()

    signed_in.post(account_url("account_edit", bank), edit_data(bank, ""))

    bank.refresh_from_db()
    assert bank.low_balance_threshold == Decimal(0)


def test_a_new_account_offers_a_threshold_of_zero(signed_in: Client) -> None:
    page = signed_in.get(reverse("account_create", kwargs={"kind": "asset"}))

    assert 'name="low_balance_threshold" value="0"' in page.content.decode()


def test_expense_accounts_have_no_threshold(signed_in: Client) -> None:
    page = signed_in.get(reverse("account_create", kwargs={"kind": "expense"}))

    assert "low_balance_threshold" not in page.content.decode()
