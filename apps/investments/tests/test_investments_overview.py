from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, page_text
from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument
from apps.investments.tests.conftest import (
    add_price,
    instrument_url,
    make_broker,
    record_event,
)
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
SOLD = "INE000000002"


def overview(client: Client) -> str:
    response = client.get(reverse("investments_overview"))
    assert response.status_code == 200
    return response.content.decode()


def test_the_overview_lists_investment_accounts_and_instruments_held(
    signed_in: Client,
) -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=SOLD, name="Acme Ltd", kind="stock")
    opening("Bank", "asset", "100")
    broker = make_broker("Zerodha", opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", price="100", amount="1000")
    record_event(signed_in, broker, "buy", SOLD, units="1", price="50", amount="50")
    record_event(signed_in, broker, "sell", SOLD, units="1", price="60", amount="60")
    add_price(FUND, date(2026, 3, 5), "150")

    html = overview(signed_in)

    text = page_text(html)
    assert "Zerodha ₹10,510.00" in text
    assert "Nifty Fund 10 ₹1,500.00" in text
    assert "Bank" not in text
    assert "Acme Ltd" not in text
    assert f'href="{account_url("account_transactions", broker)}"' in html
    assert f'href="{instrument_url(FUND)}"' in html


def test_investments_is_marked_in_the_nav_on_instrument_pages(
    signed_in: Client,
) -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")

    body = signed_in.get(instrument_url(FUND)).content.decode()

    assert f'href="{reverse("investments_overview")}" aria-current="page"' in body


def test_the_overview_says_when_there_is_nothing_yet(signed_in: Client) -> None:
    assert "No Investment Accounts yet" in page_text(overview(signed_in))


def test_privacy_mode_masks_the_overview(signed_in: Client) -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    broker = make_broker("Zerodha", opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", price="100", amount="1000")
    turn_on(signed_in, reverse("index"))

    text = page_text(overview(signed_in))

    assert "₹10" not in text
    assert "Nifty Fund 10" not in text
