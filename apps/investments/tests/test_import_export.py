import csv
import io
from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import (
    IMPORT_HEADER,
    holdings_text,
    import_line,
    import_text,
    imported,
    make_broker,
    make_direct,
    upload_import,
)
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

NEW_FUND = "INF000000002"
STOCK = "INE000000001"


@pytest.fixture(autouse=True)
def _fund() -> None:
    Instrument.objects.create(
        isin="INF000000001", name="Nifty Fund", kind="mutual_fund"
    )


def exported(client: Client) -> bytes:
    response = client.get(reverse("investment_export"))
    assert response["Content-Type"] == "text/csv"
    assert "attachment" in response["Content-Disposition"]
    return response.content


def test_the_template_has_the_header_and_an_example_of_every_type(
    signed_in: Client,
) -> None:
    response = signed_in.get(reverse("investment_import_template"))

    assert response["Content-Type"] == "text/csv"
    header, *examples = csv.reader(io.StringIO(response.content.decode()))
    assert ",".join(header) == IMPORT_HEADER
    assert [row[4] for row in examples] == [
        "BUY",
        "SELL",
        "DIVIDEND",
        "STOCK_SPLIT",
        "BONUS",
        "MERGER",
    ]


def test_the_import_page_offers_the_template_and_export(signed_in: Client) -> None:
    response = signed_in.get(reverse("investment_import"))

    page = page_text(response.content.decode())
    assert "Download the template" in page
    assert "Export Investment Events" in page


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"date,account\n", "Missing columns: isin, instrument_name, type"),
        (IMPORT_HEADER.encode(), "The file has no rows."),
    ],
)
def test_a_file_it_cant_read_says_why(
    signed_in: Client, content: bytes, problem: str
) -> None:
    page = upload_import(signed_in, content)

    assert problem in page
    assert "Confirm import" not in page


def test_a_file_that_isnt_utf8_is_refused(signed_in: Client) -> None:
    page = upload_import(signed_in, "date,₹".encode("utf-16"))

    assert "Save the file as a UTF-8 CSV" in page


def test_a_confirm_without_the_file_goes_back_to_upload(signed_in: Client) -> None:
    response = signed_in.post(reverse("investment_import_confirm"), {})

    assert response["Location"] == reverse("investment_import")


def test_export_writes_every_event_in_the_import_format(signed_in: Client) -> None:
    make_broker(opening="5000")
    rows = (
        import_line("BUY", date="2026-02-01", instrument_name="Nifty Fund",
                    units="10.5", price="100.25", amount="1052.63", charges="1.5",
                    ref="B-1", note="First"),
        import_line("DIVIDEND", date="2025-12-01", instrument_name="Nifty Fund",
                    amount="5"),
        import_line("MERGER", date="2026-02-02", instrument_name="Merged Fund",
                    new_isin=NEW_FUND),
    )  # fmt: skip
    imported(signed_in, *rows)

    lines = exported(signed_in).decode().splitlines()

    assert lines == import_text(rows[1], rows[0], rows[2]).splitlines()


def test_export_then_import_into_an_empty_database_round_trips(
    signed_in: Client,
) -> None:
    bank = opening("Bank", "asset", "10000")
    broker = make_broker(opening="5000", opened=date(2026, 6, 1))
    kuvera = make_direct(bank, opened=date(2026, 6, 1))
    imported(
        signed_in,
        import_line("BUY", date="2026-02-01", units="10", price="100",
                    amount="1000"),
        import_line("BUY", account="Kuvera", date="2026-01-05", isin=STOCK,
                    instrument_name="Unlisted Co", units="3.123456",
                    price="12.3456", amount="38.56", charges="0.4"),
        import_line("SELL", date="2026-02-01", units="1", price="100",
                    amount="100"),
        import_line("DIVIDEND", date="2026-03-01", amount="7.5", ref="D-1"),
        import_line("STOCK_SPLIT", account="Kuvera", date="2026-02-10",
                    isin=STOCK, units="2"),
        import_line("BONUS", date="2026-03-01", units="1"),
        import_line("MERGER", date="2026-03-02", instrument_name="Merged Fund",
                    new_isin=NEW_FUND),
        import_line("SELL", date="2026-03-03", isin=NEW_FUND, units="5",
                    price="120", amount="600", note="part"),
    )  # fmt: skip
    first = exported(signed_in)
    holdings = holdings_text(signed_in, broker), holdings_text(signed_in, kuvera)
    InvestmentEvent.objects.all().delete()
    Instrument.objects.all().delete()

    imported(signed_in, *first.decode().splitlines()[1:])

    assert exported(signed_in) == first
    assert (holdings_text(signed_in, broker), holdings_text(signed_in, kuvera)) == (
        holdings
    )


def test_export_and_import_are_blocked_in_privacy_mode(signed_in: Client) -> None:
    turn_on(signed_in)

    for name in ("investment_export", "investment_import"):
        url = reverse(name)
        response = signed_in.get(url)
        assert response["Location"] == privacy_mode_off_url(url)
