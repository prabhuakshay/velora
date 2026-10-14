from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.accounts.tests.test_balance import opening, record
from apps.investments.models import Instrument, InvestmentEvent, PriceSource
from apps.investments.tests.conftest import (
    holdings_text,
    import_confirm,
    import_line,
    import_preview,
    imported,
    instrument_page,
    make_broker,
    make_direct,
)
from apps.quick_add.models import Draft
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

NEW_FUND = "INF000000002"
STOCK = "INE000000001"


@pytest.fixture(autouse=True)
def _fund() -> None:
    Instrument.objects.create(
        isin="INF000000001", name="Nifty Fund", kind="mutual_fund"
    )


def buy(**fields: str) -> str:
    return import_line(
        "BUY", **({"units": "10", "price": "100", "amount": "1000"} | fields)
    )


def sell(units: str, amount: str, **fields: str) -> str:
    return import_line("SELL", units=units, amount=amount, **fields)


def drafts_text(client: Client) -> str:
    return page_text(client.get(reverse("draft_list")).content.decode())


def account_text(client: Client, account: Account) -> str:
    return page_text(
        client.get(account_url("account_transactions", account)).content.decode()
    )


def test_the_preview_lists_rows_to_add_and_changes_nothing(signed_in: Client) -> None:
    broker = make_broker()

    page = import_preview(signed_in, buy(), sell("4", "440"))

    assert "2 to add · 0 already recorded · 0 with errors" in page
    assert "Confirm import" in page
    assert "Nothing held yet" in holdings_text(signed_in, broker)


def test_confirming_applies_every_row(signed_in: Client) -> None:
    broker = make_broker(opening="5000")
    rows = (buy(), sell("4", "440", charges="2"))
    import_preview(signed_in, *rows)

    response = import_confirm(signed_in, *rows)

    assert response.status_code == 302
    page = holdings_text(signed_in, broker)
    assert "Nifty Fund 6 ₹600.00" in page
    assert "Cash ₹4,438.00" in page


def test_rows_apply_in_date_order_whatever_the_file_order(signed_in: Client) -> None:
    broker = make_broker(opening="5000")

    imported(signed_in, sell("4", "440", date="2026-03-05"), buy(date="2026-03-05"))

    assert "Nifty Fund 6 ₹600.00" in holdings_text(signed_in, broker)


def test_each_error_row_gives_its_reason(signed_in: Client) -> None:
    make_broker()

    page = import_preview(
        signed_in,
        buy(date="2026-02-30"),
        buy(account="Groww"),
        import_line("SWAP"),
        import_line("BUY", units="10", price="100"),
        buy(isin="INE999999999"),
        buy(ref="x" * 101),
        buy(units="ten"),
    )

    assert "0 to add · 0 already recorded · 7 with errors" in page
    assert "date: Use a date like 2026-03-31." in page
    assert "account: No Investment Account is named “Groww”." in page
    assert "type: Use one of BUY, BONUS, STOCK_SPLIT, MERGER, DIVIDEND, SELL." in page
    assert "amount: This field is required." in page
    assert "instrument_name: Velora doesn&#x27;t know this ISIN" in page
    assert "ref: Keep it to 100 characters." in page
    assert "units: Enter a number." in page
    assert "Confirm import" not in page


def test_a_sell_of_more_units_than_the_file_bought_is_an_error(
    signed_in: Client,
) -> None:
    make_broker(opening="5000")

    page = import_preview(signed_in, buy(), sell("11", "1100"))

    assert "Only 10 units of Nifty Fund were held on 2 Mar 2026." in page


def test_one_bad_row_blocks_the_whole_import(signed_in: Client) -> None:
    broker = make_broker(opening="5000")

    response = import_confirm(signed_in, buy(), buy(account="Groww"))

    assert response.status_code == 200
    assert "1 with errors" in page_text(response.content.decode())
    assert "Nothing held yet" in holdings_text(signed_in, broker)


def test_uploading_the_same_file_twice_adds_nothing_the_second_time(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="5000")
    rows = (
        buy(),
        buy(date="2026-03-03", ref="A-2"),
        import_line("DIVIDEND", date="2025-12-01", amount="5"),
    )
    imported(signed_in, *rows)

    page = import_preview(signed_in, *rows)
    imported(signed_in, *rows)

    assert "0 to add · 3 already recorded · 0 with errors" in page
    assert "Nifty Fund 20 ₹2,000.00" in holdings_text(signed_in, broker)


def test_a_repeated_ref_is_a_duplicate_even_with_other_values(
    signed_in: Client,
) -> None:
    make_broker(opening="5000")

    page = import_preview(signed_in, buy(ref="A-1"), buy(date="2026-03-04", ref="A-1"))

    assert "1 to add · 1 already recorded · 0 with errors" in page


def test_rows_before_the_opening_balance_date_post_no_transactions(
    signed_in: Client,
) -> None:
    bank = opening("Bank", "asset", "10000")
    kuvera = make_direct(bank, opened=date(2026, 2, 1))

    imported(
        signed_in,
        buy(account="Kuvera", date="2026-01-10"),
        sell("2", "240", account="Kuvera", date="2026-01-20"),
        import_line("DIVIDEND", account="Kuvera", date="2026-02-01", amount="15"),
    )

    assert not Transaction.objects.exists()
    assert "Nifty Fund 8 ₹800.00" in holdings_text(signed_in, kuvera)
    assert "Balance ₹10,000.00" in account_text(signed_in, bank)


def test_a_later_direct_buy_links_the_transaction_already_recorded(
    signed_in: Client,
) -> None:
    bank = opening("Bank", "asset", "10000")
    kuvera = make_direct(bank)
    record(signed_in, bank, kuvera, "1005.00")
    recorded = Transaction.objects.get()
    row = buy(account="Kuvera", date="2026-03-04", charges="5")

    page = import_preview(signed_in, row)
    imported(signed_in, row)

    assert "Matches the Transaction on 1 Mar 2026" in page
    assert Transaction.objects.get() == recorded
    assert InvestmentEvent.objects.get().transaction == recorded
    assert "Balance ₹8,995.00" in account_text(signed_in, bank)
    assert "Cash ₹0.00" in holdings_text(signed_in, kuvera)


def test_a_later_direct_buy_with_no_transaction_becomes_a_draft(
    signed_in: Client,
) -> None:
    bank = opening("Bank", "asset", "10000")
    kuvera = make_direct(bank)
    record(signed_in, bank, kuvera, "1000.00")
    row = buy(account="Kuvera", date="2026-03-05", charges="5")

    page = import_preview(signed_in, row)
    response = import_confirm(signed_in, row)

    assert "Becomes a Draft to review" in page
    assert response.status_code == 302
    drafts = drafts_text(signed_in)
    assert "Imported 0 Investment Events and 1 Draft to review" in drafts
    assert "Buy Nifty Fund ₹1,005.00" in drafts
    assert "Buy Nifty Fund in Kuvera · 10 units at ₹100.0000 Bank Kuvera" in drafts
    assert "Investment Import Post" in drafts
    assert not InvestmentEvent.objects.exists()
    assert "Nothing held yet" in holdings_text(signed_in, kuvera)


def test_one_transaction_matches_only_one_row(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "10000")
    kuvera = make_direct(bank)
    record(signed_in, bank, kuvera, "1000.00")

    page = import_preview(
        signed_in, buy(account="Kuvera"), buy(account="Kuvera", ref="second")
    )

    assert "Matches the Transaction on 1 Mar 2026" in page
    assert "Becomes a Draft to review" in page


def test_a_later_direct_sell_matches_its_proceeds(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "10000")
    kuvera = make_direct(bank, opened=date(2026, 2, 1))
    record(signed_in, kuvera, bank, "395.00")

    imported(
        signed_in,
        buy(account="Kuvera", date="2026-01-10"),
        sell("4", "400", account="Kuvera", charges="5"),
    )

    sell_event = InvestmentEvent.objects.get(kind="sell")
    assert sell_event.transaction == Transaction.objects.get()


def test_a_later_dividend_links_its_income_transaction(signed_in: Client) -> None:
    dividends = make_account("Dividends", "income")
    broker = make_broker(opening="5000")
    record(signed_in, dividends, broker, "75.00")

    imported(signed_in, buy(), import_line("DIVIDEND", date="2026-02-27", amount="75"))

    event = InvestmentEvent.objects.get(kind="dividend")
    assert event.transaction == Transaction.objects.get()
    assert "Balance ₹5,075.00" in account_text(signed_in, broker)


def test_an_unknown_isin_creates_an_instrument(signed_in: Client) -> None:
    make_broker(opening="5000")

    imported(signed_in, buy(isin=STOCK.lower(), instrument_name="Unlisted Co"))

    assert "Unlisted Co" in instrument_page(signed_in, STOCK)
    assert Instrument.objects.get(isin=STOCK).price_source == PriceSource.NSE


def test_a_merger_can_name_its_new_instrument(signed_in: Client) -> None:
    broker = make_broker(opening="5000")

    imported(
        signed_in,
        buy(date="2026-02-01"),
        import_line("MERGER", instrument_name="Merged Fund", new_isin=NEW_FUND),
    )

    assert "Merged Fund 10 ₹1,000.00" in holdings_text(signed_in, broker)


def test_a_merger_into_an_unknown_unnamed_isin_is_an_error(signed_in: Client) -> None:
    make_broker(opening="5000")

    page = import_preview(
        signed_in, buy(date="2026-02-01"), import_line("MERGER", new_isin=NEW_FUND)
    )

    assert "new_isin: Velora doesn&#x27;t know this ISIN." in page


def test_stock_split_and_bonus_rows(signed_in: Client) -> None:
    broker = make_broker(opening="5000")

    imported(
        signed_in,
        buy(date="2026-02-01"),
        import_line("STOCK_SPLIT", units="2"),
        import_line("BONUS", date="2026-03-03", units="5"),
    )

    assert "Nifty Fund 25 ₹1,000.00" in holdings_text(signed_in, broker)


def post_drafts(client: Client) -> None:
    response = client.post(reverse("draft_post_all"))
    assert response.status_code == 302


@pytest.mark.parametrize("ref", ["", "K-7"])
def test_a_posted_import_draft_is_recorded_once_whatever_is_uploaded_after(
    signed_in: Client, ref: str
) -> None:
    bank = opening("Bank", "asset", "10000")
    kuvera = make_direct(bank)
    row = buy(account="Kuvera", date="2026-03-05", charges="5", ref=ref, note="SIP")
    imported(signed_in, row)

    post_drafts(signed_in)
    page = import_preview(signed_in, row)
    imported(signed_in, row)

    assert "0 to add · 1 already recorded · 0 with errors" in page
    event = InvestmentEvent.objects.get()
    assert (event.ref, event.note) == (ref, "SIP")
    assert event.transaction == Transaction.objects.get()
    assert "Nifty Fund 10 ₹1,005.00" in holdings_text(signed_in, kuvera)
    assert "Balance ₹8,995.00" in account_text(signed_in, bank)


@pytest.mark.parametrize("ref", ["", "K-7"])
def test_uploading_again_before_posting_proposes_no_second_draft(
    signed_in: Client, ref: str
) -> None:
    make_direct(opening("Bank", "asset", "10000"))
    row = buy(account="Kuvera", date="2026-03-05", ref=ref)
    imported(signed_in, row)

    page = import_preview(signed_in, row)
    imported(signed_in, row)

    assert "0 to add · 1 already recorded · 0 with errors" in page
    assert "Drafts 1 " in drafts_text(signed_in)


def test_a_rejected_import_draft_is_proposed_again(signed_in: Client) -> None:
    make_direct(opening("Bank", "asset", "10000"))
    row = buy(account="Kuvera", date="2026-03-05", ref="K-7")
    imported(signed_in, row)
    draft = Draft.objects.get()
    signed_in.post(reverse("draft_reject", args=[draft.pk]))

    page = import_preview(signed_in, row)

    assert "1 to add · 0 already recorded · 0 with errors" in page


def test_a_later_dividend_with_no_transaction_waits_for_its_income_account(
    signed_in: Client,
) -> None:
    broker = make_broker(opening="5000")

    imported(signed_in, buy(), import_line("DIVIDEND", date="2026-03-04", amount="75"))
    post_drafts(signed_in)

    assert "Dividend Nifty Fund ₹75.00" in drafts_text(signed_in)
    assert not InvestmentEvent.objects.filter(kind="dividend").exists()
    assert "Balance ₹5,000.00" in account_text(signed_in, broker)


def test_a_draft_row_can_bring_an_unknown_instrument(signed_in: Client) -> None:
    make_direct(opening("Bank", "asset", "10000"))

    imported(
        signed_in,
        buy(account="Kuvera", isin=STOCK, instrument_name="Unlisted Co"),
    )

    assert "Buy Unlisted Co in Kuvera" in drafts_text(signed_in)
    assert Instrument.objects.get(isin=STOCK).price_source == PriceSource.NSE
