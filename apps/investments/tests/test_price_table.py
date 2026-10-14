import re
from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.investments.models import Instrument, PriceFetch
from apps.investments.prices import fetch_today
from apps.investments.tasks import refresh_prices
from apps.investments.tests.conftest import instrument_url, row
from apps.quick_add.tests.test_migrations import migrate

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.tests.conftest import FakePrices
    from apps.users.models import User

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 14)
STOCK = "INE002A01018"
FUND = "INF209KA12Z1"


def price_rows(
    client: Client, isin: str | None = STOCK, url: str | None = None
) -> list[str]:
    """Each row of the Instrument page's Price table, newest first."""
    html = client.get(url or instrument_url(isin)).content.decode()
    return [
        unescape(page_text(found))
        for found in re.findall(r"<tr data-price>(.*?)</tr>", html, re.DOTALL)
    ]


def fetched_at() -> str:
    return f"fetched {timezone.localtime():%-d %b}"


def test_a_fetched_price_shows_its_file_and_fetch(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    file_day = timezone.localdate() - timedelta(days=1)
    fake_prices.nse = [row(STOCK, "Reliance", "stock", "2950", file_day)]

    refresh_prices()

    (only,) = price_rows(signed_in)
    assert f"{file_day:%-d %b %Y}" in only
    assert "₹2,950.0000" in only
    assert f"NSE · {file_day:%-d %b} file · {fetched_at()}" in only
    assert only.endswith("by Refresh")


def test_a_price_keeps_its_source_once_its_fetch_is_removed(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [row(FUND, "A fund", "mutual_fund", "10", TODAY)]
    fetch_today(TODAY)

    PriceFetch.objects.all().delete()

    assert price_rows(signed_in, FUND) == ["14 Oct 2026 ₹10.0000 — AMFI"]


def manual_instrument() -> Instrument:
    return Instrument.objects.create(isin=None, name="Unlisted Co", kind="stock")


def enter_price(client: Client, instrument: Instrument, day: str, price: str) -> None:
    client.post(
        reverse("instrument_add_price", args=[instrument.pk]),
        {"date": day, "price": price},
    )


def test_prices_list_newest_first_with_their_change(signed_in: Client) -> None:
    instrument = manual_instrument()
    enter_price(signed_in, instrument, "2026-10-01", "100")
    enter_price(signed_in, instrument, "2026-10-03", "90.5")
    enter_price(signed_in, instrument, "2026-10-02", "110")

    entered = f"Manual · entered {timezone.localdate():%-d %b}"
    assert price_rows(signed_in, None) == [
        f"3 Oct 2026 ₹90.5000 -₹19.5000 {entered}",
        f"2 Oct 2026 ₹110.0000 +₹10.0000 {entered}",
        f"1 Oct 2026 ₹100.0000 — {entered}",
    ]


def test_the_table_shows_30_prices_then_more_on_asking(signed_in: Client) -> None:
    instrument = manual_instrument()
    first = date(2026, 1, 1)
    for n in range(31):
        enter_price(signed_in, instrument, f"{first + timedelta(days=n)}", "10")

    shown = price_rows(signed_in, None)
    assert len(shown) == 30
    assert shown[-1].startswith("2 Jan 2026 ₹10.0000 ₹0.0000")
    html = signed_in.get(instrument_url(None)).content.decode()
    more = re.search(r'href="([^"]*)"[^>]*>Show more<', html)
    assert more
    more_url = instrument_url(None) + unescape(more[1])

    assert len(price_rows(signed_in, url=more_url)) == 31
    assert "Show more" not in signed_in.get(more_url).content.decode()


def source_line(client: Client, isin: str | None) -> str:
    html = client.get(instrument_url(isin)).content.decode()
    found = re.search(r"<p data-price-source[^>]*>(.*?)</p>", html, re.DOTALL)
    assert found, html
    return unescape(page_text(found[1]))


def test_the_page_states_its_price_source_and_last_fetch(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.nse = [row(STOCK, "Reliance", "stock", "2950", TODAY)]
    fake_prices.amfi = [row(FUND, "A fund", "mutual_fund", "10", TODAY)]
    fetch_today(TODAY)

    assert source_line(signed_in, STOCK).startswith(
        f"Price Source: NSE · last {fetched_at()}"
    )
    assert source_line(signed_in, FUND).startswith("Price Source: AMFI · last fetched")


def test_a_manual_instrument_states_it_is_priced_by_hand(signed_in: Client) -> None:
    manual_instrument()

    assert source_line(signed_in, None) == "Price Source: Manual"


def test_privacy_mode_hides_the_table(signed_in: Client, user: User) -> None:
    instrument = manual_instrument()
    enter_price(signed_in, instrument, "2026-10-01", "4321")
    user.privacy_mode = True
    user.save()

    html = signed_in.get(instrument_url(None)).content.decode()

    assert price_rows(signed_in, None) == []
    assert "4,321" not in html


BEFORE_SOURCES = [("investments", "0009_price_fetch")]


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_prices_stored_before_sources_show_their_instruments_source(
    signed_in: Client,
) -> None:
    old = migrate(BEFORE_SOURCES).loader.project_state(BEFORE_SOURCES).apps
    instruments = old.get_model("investments", "Instrument").objects
    prices = old.get_model("investments", "Price").objects
    for isin, kind, manual in [
        (FUND, "mutual_fund", False),
        (STOCK, "stock", False),
        ("INE000000001", "stock", True),
    ]:
        instrument = instruments.create(
            isin=isin, name=isin, kind=kind, manual_price=manual
        )
        prices.create(instrument=instrument, date=TODAY, price=Decimal(10))

    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    assert price_rows(signed_in, FUND) == ["14 Oct 2026 ₹10.0000 — AMFI"]
    assert price_rows(signed_in, STOCK) == ["14 Oct 2026 ₹10.0000 — NSE"]
    # The made-up ISIN is cleared later, so the Instrument is the one without.
    assert price_rows(signed_in, None) == ["14 Oct 2026 ₹10.0000 — Manual"]
