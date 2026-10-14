import re
from datetime import timedelta
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.investments.models import Instrument
from apps.investments.nightly import run_nightly_prices
from apps.investments.tests.conftest import (
    add_price,
    make_broker,
    record_event,
    row,
)
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.investments.tests.conftest import FakePriceSource

pytestmark = pytest.mark.django_db

FUND = "INF209KA12Z1"
STOCK = "INE002A01018"
OTHER = "INE000000099"


def holding(client: Client, isin: str, name: str, kind: str, **fields: bool) -> Account:
    Instrument.objects.create(isin=isin, name=name, kind=kind, **fields)
    account = make_broker()
    record_event(client, account, "buy", isin, units="2", amount="100")
    return account


def overview_row(client: Client, name: str) -> str:
    html = client.get(reverse("investments_overview")).content.decode()
    return _row(html, name)


def holdings_row(client: Client, account: Account, name: str) -> str:
    html = client.get(reverse("account_holdings", args=[account.pk])).content.decode()
    return _row(html, name)


def _row(html: str, name: str) -> str:
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    found = [r for r in rows if name in r]
    assert found, html
    return unescape(page_text(found[0]))


def test_an_unpriced_fetched_holding_says_it_was_not_in_the_latest_file(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    account = holding(signed_in, STOCK, "Tejas Networks", "stock")
    fake_prices.nse = [row(OTHER, "Other Ltd", "stock", "10", yesterday)]
    run_nightly_prices(today)

    expected = f"Not in NSE's {yesterday:%-d %b} file"
    assert expected in overview_row(signed_in, "Tejas Networks")
    assert expected in holdings_row(signed_in, account, "Tejas Networks")


def test_a_priced_holding_shows_its_price_date_and_source(signed_in: Client) -> None:
    today = timezone.localdate()
    account = holding(signed_in, FUND, "Nifty Fund", "mutual_fund")
    add_price(FUND, today, "1234.5")

    expected = f"₹1,234.5000 · {today:%-d %b %Y} · AMFI"
    assert expected in overview_row(signed_in, "Nifty Fund")
    assert expected in holdings_row(signed_in, account, "Nifty Fund")


def test_an_unpriced_manual_holding_links_to_the_price_form(signed_in: Client) -> None:
    account = holding(signed_in, STOCK, "Private Co", "stock", manual_price=True)
    form = reverse("instrument_detail", args=[Instrument.objects.get(isin=STOCK).pk])

    assert "Priced by hand: add a Price" in overview_row(signed_in, "Private Co")
    assert "Priced by hand: add a Price" in holdings_row(
        signed_in, account, "Private Co"
    )
    html = signed_in.get(reverse("investments_overview")).content.decode()
    assert f'href="{form}#enter-price"' in html
    assert 'id="enter-price"' in signed_in.get(form).content.decode()


def test_a_stale_price_badge_names_its_source(signed_in: Client) -> None:
    account = holding(signed_in, STOCK, "Acme Ltd", "stock")
    add_price(STOCK, timezone.localdate() - timedelta(days=6), "45")

    assert "Stale NSE Price" in overview_row(signed_in, "Acme Ltd")
    assert "Stale NSE Price" in holdings_row(signed_in, account, "Acme Ltd")


def test_an_unpriced_holding_never_fetched_says_no_price_yet(
    signed_in: Client,
) -> None:
    holding(signed_in, STOCK, "Acme Ltd", "stock")

    assert "No Price yet · NSE" in overview_row(signed_in, "Acme Ltd")


def test_privacy_mode_hides_holding_prices(signed_in: Client) -> None:
    account = holding(signed_in, FUND, "Nifty Fund", "mutual_fund")
    add_price(FUND, timezone.localdate(), "1234.5")
    turn_on(signed_in)

    assert (
        "1,234.5" not in signed_in.get(reverse("investments_overview")).content.decode()
    )
    assert "1,234.5" not in holdings_row(signed_in, account, "Nifty Fund")
    assert "₹•••• ·" in overview_row(signed_in, "Nifty Fund")
