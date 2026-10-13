from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import account_url, page_text
from apps.investments.tests.conftest import make_broker

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def create(client: Client, kind: str, **fields: str) -> Account:
    data = {
        "name": "Zerodha",
        "opening_balance": "0",
        "opening_balance_date": "2026-01-01",
    }
    response = client.post(reverse("account_create", args=[kind]), data | fields)
    assert response.status_code == 302
    return Account.objects.get(name="Zerodha")


def test_an_asset_account_can_be_created_as_one_that_holds_cash(
    signed_in: Client,
) -> None:
    broker = create(signed_in, "asset", investment_mode="holds_cash")

    page = page_text(
        signed_in.get(account_url("account_transactions", broker)).content.decode()
    )
    assert "Investment Account · Holds Cash" in page


def test_an_asset_account_is_not_an_investment_account_unless_asked(
    signed_in: Client,
) -> None:
    bank = create(signed_in, "asset")

    assert not bank.is_investment


def test_the_investment_mode_cant_be_changed_later(signed_in: Client) -> None:
    broker = make_broker("Zerodha")
    data = {
        "name": "Zerodha",
        "opening_balance": "0",
        "opening_balance_date": "2026-01-01",
        "investment_mode": "",
    }

    response = signed_in.post(account_url("account_edit", broker), data)

    assert response.status_code == 302
    broker.refresh_from_db()
    assert broker.investment_mode == "holds_cash"


def test_only_asset_accounts_offer_the_investment_mode(signed_in: Client) -> None:
    asset = signed_in.get(reverse("account_create", args=["asset"])).content.decode()
    liability = signed_in.get(
        reverse("account_create", args=["liability"])
    ).content.decode()

    assert 'name="investment_mode"' in asset
    assert 'name="investment_mode"' not in liability
