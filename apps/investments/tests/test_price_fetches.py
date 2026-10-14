import re
from datetime import date
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.investments.models import (
    Instrument,
    InvestmentEvent,
    PriceFetch,
    PriceSource,
)
from apps.investments.prices import SOURCES, PriceFetchError, backfill, fetch_today
from apps.investments.tasks import refresh_prices
from apps.investments.tests.conftest import (
    make_broker,
    not_published,
    row,
    unreachable,
)
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.price_source import PriceRow
    from apps.investments.tests.conftest import FakePrices

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 14)
FUND = "INF209KA12Z1"
STOCK = "INE002A01018"


def fund(day: date = TODAY, isin: str = FUND) -> PriceRow:
    return row(isin, "A fund", "mutual_fund", "10", day)


def stock(day: date = TODAY, isin: str = STOCK) -> PriceRow:
    return row(isin, "Reliance Industries", "stock", "2950", day)


def status(client: Client, source: str) -> str:
    """The overview's status line for one Price Source."""
    html = client.get(reverse("investments_overview")).content.decode()
    found = re.search(rf'<li data-source="{source}">(.*?)</li>', html, re.DOTALL)
    assert found, html
    return unescape(page_text(found.group(1)))


def overview(client: Client) -> str:
    return unescape(
        page_text(client.get(reverse("investments_overview")).content.decode())
    )


def test_the_overview_shows_what_the_nightly_run_fetched(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [fund(), fund(isin="INF000000093")]

    fetch_today(TODAY)

    assert status(signed_in, "AMFI") == (
        f"AMFI · Prices for 14 Oct · checked {timezone.localtime():%H:%M} · 2 new"
    )


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (not_published(), "NSE has no file for 14 Oct"),
        (unreachable(), "NSE couldn't be reached"),
        (ValueError("bad zip"), "unexpected error: bad zip"),
    ],
)
def test_a_failed_fetch_shows_why_and_the_other_source_still_runs(
    signed_in: Client, fake_prices: FakePrices, error: Exception, reason: str
) -> None:
    fake_prices.nse = error
    fake_prices.amfi = [fund()]

    with pytest.raises(PriceFetchError, match="NSE"):
        fetch_today(TODAY)

    assert f"NSE Price Fetch failed: {reason}" in overview(signed_in)
    assert "last check failed" in status(signed_in, "NSE")
    assert "1 new" in status(signed_in, "AMFI")


def test_nse_falling_back_to_an_earlier_file_shows_both_days(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.nse = [stock(date(2026, 10, 13))]

    fetch_today(TODAY)

    assert "NSE · Prices for 13 Oct · 14 Oct not out yet · checked" in status(
        signed_in, "NSE"
    )


def test_running_twice_stores_no_price_the_second_time(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [fund()]
    fetch_today(TODAY)

    fetch_today(TODAY)

    line = status(signed_in, "AMFI")
    assert "checked" in line
    assert "new" not in line


def test_a_refresh_records_its_price_fetches_as_a_refresh(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePrices
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock()]

    refresh_prices()

    assert "1 new" in status(signed_in, "AMFI")
    assert "1 new" in status(signed_in, "NSE")
    assert PriceFetch.objects.filter(trigger=PriceFetch.Trigger.REFRESH).count() == 2


def test_privacy_mode_hides_how_many_prices_were_stored(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [fund()]
    fetch_today(TODAY)
    turn_on(signed_in, reverse("index"))

    assert status(signed_in, "AMFI").endswith("· •••• new")


def test_a_source_with_nothing_to_show_is_left_out(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.nse = [stock()]
    fetch_today(TODAY)

    html = signed_in.get(reverse("investments_overview")).content.decode()

    assert 'data-source="NSE"' in html
    assert 'data-source="AMFI"' not in html


def test_after_refresh_each_source_shows_as_fetching(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [fund()]
    fetch_today(TODAY, PriceFetch.Trigger.NIGHTLY)

    signed_in.post(reverse("investments_refresh_prices"))

    assert status(signed_in, "AMFI") == "AMFI · Prices for 14 Oct · checking…"
    assert status(signed_in, "NSE") == "NSE · No Prices yet · checking…"


POLL = 'hx-trigger="every 2s"'


def status_partial(client: Client) -> str:
    response = client.get(reverse("investments_price_status"))
    assert response.status_code == 200
    return response.content.decode()


def test_the_status_line_polls_while_a_refresh_is_queued(signed_in: Client) -> None:
    signed_in.post(reverse("investments_refresh_prices"))

    partial = status_partial(signed_in)

    assert POLL in partial
    assert f'hx-get="{reverse("investments_price_status")}"' in partial
    assert POLL in signed_in.get(reverse("investments_overview")).content.decode()


def test_the_status_line_stops_polling_once_fetches_finish(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [fund()]
    fetch_today(TODAY)

    partial = status_partial(signed_in)

    assert POLL not in partial
    assert "1 new" in unescape(page_text(partial))
    assert POLL not in signed_in.get(reverse("investments_overview")).content.decode()


def test_the_status_line_polls_while_a_fetch_runs(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePrices
) -> None:
    seen = []

    def latest(day: date) -> list[PriceRow]:
        seen.append(status_partial(signed_in))
        return [fund()]

    monkeypatch.setattr(SOURCES[PriceSource.AMFI], "latest", latest)

    fetch_today(TODAY)

    assert POLL in seen[0]
    assert "AMFI · No Prices yet · checking…" in unescape(page_text(seen[0]))


def test_a_second_refresh_press_shows_the_one_already_waiting(
    signed_in: Client,
) -> None:
    first = signed_in.post(reverse("investments_refresh_prices"), follow=True)
    second = signed_in.post(reverse("investments_refresh_prices"), follow=True)

    assert "Refreshing Prices" in first.content.decode()
    text = unescape(page_text(second.content.decode()))
    assert "A Refresh is already waiting to start" in text
    assert "NSE · No Prices yet · checking…" in text


def test_a_finished_refresh_shows_prices_stored_and_the_day_nse_used(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePrices
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock(date(2026, 10, 13))]

    refresh_prices()

    text = unescape(page_text(status_partial(signed_in)))
    assert "AMFI · Prices for 14 Oct · checked" in text
    assert "NSE · Prices for 13 Oct · 14 Oct not out yet · checked" in text
    assert text.count("1 new") == 2


def test_the_status_partial_needs_sign_in(client: Client) -> None:
    response = client.get(reverse("investments_price_status"))

    assert response["Location"].startswith(reverse("login"))


def test_privacy_mode_hides_counts_in_the_status_partial(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.amfi = [fund()]
    fetch_today(TODAY)
    turn_on(signed_in, reverse("index"))

    assert "•••• new" in unescape(page_text(status_partial(signed_in)))


def test_the_polled_status_line_carries_the_failure_banner(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    fake_prices.nse = unreachable()
    with pytest.raises(PriceFetchError):
        fetch_today(TODAY)

    assert 'data-fetch-failed="NSE"' in status_partial(signed_in)


def hold(isin: str, kind: str, since: date) -> None:
    InvestmentEvent.objects.create(
        account=make_broker(f"Broker {isin}"),
        instrument=Instrument.objects.get_or_create(
            isin=isin, defaults={"name": isin, "kind": kind}
        )[0],
        kind="buy",
        date=since,
        units=1,
        amount=10,
    )


def test_a_backfill_shows_the_range_it_filled_and_what_it_stored(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    hold(FUND, "mutual_fund", date(2026, 10, 12))
    fake_prices.history = [fund(date(2026, 10, d)) for d in (12, 13, 14)]

    backfill(today=TODAY)

    line = status(signed_in, "AMFI")
    assert line.startswith("AMFI · Prices for 14 Oct · checked")
    assert line.endswith("· 3 new")


def test_a_failed_backfill_source_shows_why_and_the_other_still_fills(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    hold(FUND, "mutual_fund", date(2026, 10, 13))
    hold(STOCK, "stock", date(2026, 10, 13))
    fake_prices.amfi_history = unreachable()
    fake_prices.history = [stock(date(2026, 10, 13)), stock()]

    with pytest.raises(PriceFetchError, match="AMFI"):
        backfill(today=TODAY)

    assert "AMFI Price Fetch failed: AMFI couldn't be reached" in overview(signed_in)
    assert "2 new" in status(signed_in, "NSE")


def test_a_backfill_keeps_the_windows_that_worked_when_a_later_one_fails(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    hold(FUND, "mutual_fund", date(2026, 9, 1))
    fake_prices.history = [fund(date(2026, 9, d)) for d in (1, 2)] + [fund()]
    fake_prices.history_failures = {TODAY: unreachable()}

    with pytest.raises(PriceFetchError, match="AMFI"):
        backfill(today=TODAY)

    assert status(signed_in, "AMFI") == ("AMFI · Prices for 2 Sep · last check failed")
    assert "AMFI Price Fetch failed: AMFI couldn't be reached" in overview(signed_in)


def test_a_refresh_with_nothing_to_backfill_still_shows_the_refresh(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePrices
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    hold(FUND, "mutual_fund", TODAY)
    hold(STOCK, "stock", TODAY)
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock()]

    refresh_prices()

    assert fake_prices.fetched == []
    assert "1 new" in status(signed_in, "AMFI")
    assert "1 new" in status(signed_in, "NSE")


def test_a_refresh_keeps_its_result_on_the_status_line_after_its_backfill(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePrices
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    hold(FUND, "mutual_fund", date(2026, 10, 12))
    hold(STOCK, "stock", date(2026, 10, 12))
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock(date(2026, 10, 13))]
    fake_prices.history = [fund(date(2026, 10, d)) for d in (12, 13)] + [
        stock(date(2026, 10, 12))
    ]

    refresh_prices()

    nse = status(signed_in, "NSE")
    assert "14 Oct not out yet" in nse
    assert nse.endswith("· 2 new")
    assert status(signed_in, "AMFI").endswith("· 3 new")


def test_a_failed_backfill_after_a_working_refresh_still_shows_the_banner(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePrices
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    hold(FUND, "mutual_fund", date(2026, 10, 12))
    fake_prices.amfi = [fund()]
    fake_prices.amfi_history = unreachable()

    with pytest.raises(PriceFetchError):
        refresh_prices()

    assert "last check failed" in status(signed_in, "AMFI")
    assert 'data-fetch-failed="AMFI"' in status_partial(signed_in)


def test_a_backfill_with_no_file_names_the_range(
    signed_in: Client, fake_prices: FakePrices
) -> None:
    hold(STOCK, "stock", date(2026, 10, 12))
    fake_prices.nse_history = not_published()

    with pytest.raises(PriceFetchError):
        backfill(today=TODAY)

    assert "NSE has no file for a day in 12 Oct to 14 Oct" in overview(signed_in)
