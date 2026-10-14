from datetime import date
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.accounts.tests.test_account_transactions import view_page
from apps.accounts.tests.test_reconciliation import reconcile
from apps.investments.models import Instrument
from apps.investments.tests.conftest import make_broker, make_direct, record_event
from apps.investments.tests.test_dividends import record_dividend

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000010"


@pytest.fixture(autouse=True)
def _instrument() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


def test_reconciling_a_holds_cash_account_checks_its_cash(signed_in: Client) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")

    page = page_text(reconcile(signed_in, broker, date(2026, 3, 1), "9000"))

    assert "Reconciled through 1 Mar 2026" in page


def test_a_holds_cash_account_matching_its_balance_is_off_by_its_cost_basis(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")

    page = page_text(reconcile(signed_in, broker, date(2026, 3, 1), "10000"))

    assert "That doesn&#x27;t match Velora&#x27;s Cash on 1 Mar 2026." in page
    assert "Velora's Cash ₹9,000.00 Off by ₹1,000.00" in page
    assert "Enter the Cash your broker shows for a day." in page
    assert "Date Cash Reconcile" in page


def reconciled_broker(client: Client) -> Account:
    """Holds ₹9,000 Cash and 10 units on 1 Mar 2026, reconciled that day."""
    broker = make_broker(opening="10000")
    record_event(client, broker, "buy", FUND, units="10", amount="1000")
    reconcile(client, broker, date(2026, 3, 1), "9000")
    return broker


def history_text(client: Client, account: Account) -> str:
    url = account_url("reconciliation_history", account)
    return page_text(client.get(url).content.decode())


def test_a_later_buy_dated_before_it_shows_how_far_off_it_is(
    signed_in: Client,
) -> None:
    broker = reconciled_broker(signed_in)

    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="5",
        amount="500",
        date="2026-02-15",
    )

    page = page_text(view_page(signed_in, broker))
    assert "Reconciliation on 1 Mar 2026 is off by ₹500.00" in page
    assert "Reconciled through" not in page
    assert "Off by ₹500.00" in history_text(signed_in, broker)


def test_a_later_sell_on_its_date_shows_how_far_off_it_is(signed_in: Client) -> None:
    broker = reconciled_broker(signed_in)

    record_event(signed_in, broker, "sell", FUND, units="4", amount="600")

    page = page_text(view_page(signed_in, broker))
    assert "Reconciliation on 1 Mar 2026 is off by -₹600.00" in page


def test_a_buy_after_it_leaves_it_matching(signed_in: Client) -> None:
    broker = reconciled_broker(signed_in)

    record_event(
        signed_in,
        broker,
        "buy",
        FUND,
        units="5",
        amount="500",
        date="2026-03-02",
    )

    page = page_text(view_page(signed_in, broker))
    assert "Reconciled through 1 Mar 2026" in page
    assert "Matches" in history_text(signed_in, broker)


def test_a_later_dividend_dated_before_it_shows_how_far_off_it_is(
    signed_in: Client,
) -> None:
    broker = reconciled_broker(signed_in)
    dividends = make_account("Dividends", "income")

    record_dividend(signed_in, broker, dividends, "250", day="2026-02-20")

    page = page_text(view_page(signed_in, broker))
    assert "Reconciliation on 1 Mar 2026 is off by -₹250.00" in page


def test_a_direct_account_offers_no_reconciliation(signed_in: Client) -> None:
    direct = make_direct(make_account("Bank", "asset"))

    page = view_page(signed_in, direct)

    assert "Reconcile" not in page
    url = account_url("account_reconcile", direct)
    assert (
        signed_in.post(url, {"date": "2026-03-01", "balance": "0"}).status_code == 404
    )
