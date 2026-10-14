import re
from datetime import date
from email.message import Message
from html import unescape
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.investments import price_source
from apps.investments.backfill import backfill_prices
from apps.investments.models import Instrument, InvestmentEvent, PriceFetch
from apps.investments.nightly import PriceFetchError, run_nightly_prices
from apps.investments.tasks import refresh_prices
from apps.investments.tests.conftest import make_broker, row
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.price_source import PriceRow
    from apps.investments.tests.conftest import FakePriceSource

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


def test_the_overview_shows_what_the_nightly_run_fetched(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.amfi = [fund(), fund(isin="INF000000009")]

    run_nightly_prices(TODAY)

    line = status(signed_in, "AMFI")
    assert "AMFI Prices for 14 Oct 2026" in line
    assert f"fetched {timezone.localtime():%-d %b %Y}" in line
    assert "Worked" in line
    assert "2 Prices stored" in line


def not_published() -> HTTPError:
    error = HTTPError(
        "https://nse.example/file.zip", 404, "Not Found", Message(), BytesIO()
    )
    # Nothing reads its body, and one left open warns whenever it is collected.
    error.close()
    return error


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (not_published(), "Failed: NSE has no file for 14 Oct"),
        (URLError("timed out"), "Failed: NSE couldn't be reached"),
        (ValueError("bad zip"), "Failed: unexpected error: bad zip"),
    ],
)
def test_a_failed_fetch_shows_why_and_the_other_source_still_runs(
    signed_in: Client, fake_prices: FakePriceSource, error: Exception, reason: str
) -> None:
    fake_prices.nse = error
    fake_prices.amfi = [fund()]

    with pytest.raises(PriceFetchError, match="NSE"):
        run_nightly_prices(TODAY)

    assert reason in status(signed_in, "NSE")
    assert "Worked, 1 Prices stored" in status(signed_in, "AMFI")


def test_nse_falling_back_to_an_earlier_file_shows_both_days(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.nse = [stock(date(2026, 10, 13))]

    run_nightly_prices(TODAY)

    line = status(signed_in, "NSE")
    assert "NSE Prices for 13 Oct 2026" in line
    assert "used 13 Oct, 14 Oct not out yet" in line


def test_running_twice_stores_no_price_the_second_time(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.amfi = [fund()]
    run_nightly_prices(TODAY)

    run_nightly_prices(TODAY)

    assert "Worked, 0 Prices stored" in status(signed_in, "AMFI")


def test_a_refresh_records_its_price_fetches_as_a_refresh(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePriceSource
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock()]

    refresh_prices()

    assert "by Refresh · Worked, 1 Prices stored" in status(signed_in, "AMFI")
    assert "by Refresh · Worked, 1 Prices stored" in status(signed_in, "NSE")


def test_privacy_mode_hides_how_many_prices_were_stored(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.amfi = [fund()]
    run_nightly_prices(TODAY)
    turn_on(signed_in, reverse("index"))

    line = status(signed_in, "AMFI")

    assert "Worked, •••• Prices stored" in line
    assert "AMFI Prices for 14 Oct 2026" in line


def test_a_source_never_fetched_says_so(signed_in: Client) -> None:
    assert status(signed_in, "NSE") == "NSE No Prices yet · not fetched yet"


def test_after_refresh_each_source_shows_as_fetching(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.amfi = [fund()]
    run_nightly_prices(TODAY, PriceFetch.Trigger.NIGHTLY)

    signed_in.post(reverse("investments_refresh_prices"))

    assert "fetching" in status(signed_in, "AMFI")
    assert "fetching" in status(signed_in, "NSE")
    assert "Worked" not in status(signed_in, "AMFI")


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
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.amfi = [fund()]
    run_nightly_prices(TODAY)

    partial = status_partial(signed_in)

    assert POLL not in partial
    assert "Worked, 1 Prices stored" in unescape(page_text(partial))
    assert POLL not in signed_in.get(reverse("investments_overview")).content.decode()


def test_the_status_line_polls_while_a_fetch_runs(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePriceSource
) -> None:
    seen = []

    def amfi_rows() -> list[PriceRow]:
        seen.append(status_partial(signed_in))
        return [fund()]

    monkeypatch.setattr(price_source, "amfi_rows", amfi_rows)

    run_nightly_prices(TODAY)

    assert POLL in seen[0]
    assert "AMFI No Prices yet · fetching since" in unescape(page_text(seen[0]))


def test_a_second_refresh_press_shows_the_one_already_waiting(
    signed_in: Client,
) -> None:
    first = signed_in.post(reverse("investments_refresh_prices"), follow=True)
    second = signed_in.post(reverse("investments_refresh_prices"), follow=True)

    assert "Refreshing Prices" in first.content.decode()
    text = page_text(second.content.decode())
    assert "A Refresh is already waiting to start" in text
    assert text.count("Refresh waiting to start") == 1


def test_a_finished_refresh_shows_prices_stored_and_the_day_nse_used(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePriceSource
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock(date(2026, 10, 13))]

    refresh_prices()

    text = unescape(page_text(status_partial(signed_in)))
    assert "AMFI Prices for 14 Oct 2026" in text
    assert "by Refresh · Worked, 1 Prices stored" in text
    assert "Worked, 1 Prices stored, used 13 Oct, 14 Oct not out yet" in text


def test_the_status_partial_needs_sign_in(client: Client) -> None:
    response = client.get(reverse("investments_price_status"))

    assert response["Location"].startswith(reverse("login"))


def test_privacy_mode_hides_counts_in_the_status_partial(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.amfi = [fund()]
    run_nightly_prices(TODAY)
    turn_on(signed_in, reverse("index"))

    assert "Worked, •••• Prices stored" in unescape(
        page_text(status_partial(signed_in))
    )


def test_the_polled_status_line_carries_the_failure_banner(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fake_prices.nse = URLError("timed out")
    with pytest.raises(PriceFetchError):
        run_nightly_prices(TODAY)

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
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    hold(FUND, "mutual_fund", date(2026, 10, 12))
    fake_prices.history = [fund(date(2026, 10, d)) for d in (12, 13, 14)]

    backfill_prices(today=TODAY)

    line = status(signed_in, "AMFI")
    assert "by Backfill of 12 Oct to 14 Oct · Worked, 3 Prices stored" in line
    assert "AMFI Prices for 14 Oct 2026" in line


def test_a_failed_backfill_source_shows_why_and_the_other_still_fills(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    hold(FUND, "mutual_fund", date(2026, 10, 13))
    hold(STOCK, "stock", date(2026, 10, 13))
    fake_prices.amfi_history = URLError("timed out")
    fake_prices.history = [stock(date(2026, 10, 13)), stock()]

    with pytest.raises(PriceFetchError, match="AMFI"):
        backfill_prices(today=TODAY)

    amfi = status(signed_in, "AMFI")
    assert "by Backfill of 13 Oct to 14 Oct · Failed: AMFI couldn't be reached" in amfi
    nse = status(signed_in, "NSE")
    assert "by Backfill of 13 Oct to 14 Oct · Worked, 2 Prices stored" in nse


def test_a_backfill_keeps_the_windows_that_worked_when_a_later_one_fails(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    hold(FUND, "mutual_fund", date(2026, 9, 1))
    fake_prices.history = [fund(date(2026, 9, d)) for d in (1, 2)] + [fund()]
    fake_prices.history_failures = {TODAY: URLError("timed out")}

    with pytest.raises(PriceFetchError, match="AMFI"):
        backfill_prices(today=TODAY)

    line = status(signed_in, "AMFI")
    assert "AMFI Prices for 2 Sep 2026" in line
    assert "by Backfill of 1 Sep to 14 Oct · Failed: AMFI couldn't be reached" in line


def test_a_refresh_with_nothing_to_backfill_still_shows_the_refresh(
    monkeypatch: pytest.MonkeyPatch, signed_in: Client, fake_prices: FakePriceSource
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    hold(FUND, "mutual_fund", TODAY)
    hold(STOCK, "stock", TODAY)
    fake_prices.amfi = [fund()]
    fake_prices.nse = [stock()]

    refresh_prices()

    assert fake_prices.fetched == []
    assert "by Refresh · Worked, 1 Prices stored" in status(signed_in, "AMFI")
    assert "by Refresh · Worked, 1 Prices stored" in status(signed_in, "NSE")
