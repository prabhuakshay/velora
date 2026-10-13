from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import page_text
from apps.investments import price_source
from apps.investments.models import Instrument, Price

if TYPE_CHECKING:
    from django.test import Client
    from django.test.client import _MonkeyPatchedWSGIResponse as Response


class FakePriceSource:
    """Stands in for the price-source client: hands back the rows it is given.

    A source set to an exception raises it instead, as a failed fetch would.
    History is one list for both archives; each hands back its kinds in range.
    """

    def __init__(self) -> None:
        self.amfi: list[price_source.PriceRow] | Exception = []
        self.nse: list[price_source.PriceRow] | Exception = []
        self.history: list[price_source.PriceRow] = []
        self.amfi_history: Exception | None = None
        self.nse_history: Exception | None = None
        self.fetched: list[tuple[str, date, date]] = []

    def amfi_rows(self) -> list[price_source.PriceRow]:
        if isinstance(self.amfi, Exception):
            raise self.amfi
        return self.amfi

    def nse_rows(self, day: date) -> list[price_source.PriceRow]:
        if isinstance(self.nse, Exception):
            raise self.nse
        return self.nse

    def _history(
        self, source: str, start: date, end: date, *, funds: bool
    ) -> list[price_source.PriceRow]:
        self.fetched.append((source, start, end))
        failure = self.amfi_history if funds else self.nse_history
        if failure is not None:
            raise failure
        return [
            r
            for r in self.history
            if start <= r.date <= end
            and (r.kind == Instrument.Kind.MUTUAL_FUND) == funds
        ]

    def amfi_history_rows(self, start: date, end: date) -> list[price_source.PriceRow]:
        return self._history("AMFI", start, end, funds=True)

    def nse_history_rows(self, start: date, end: date) -> list[price_source.PriceRow]:
        return self._history("NSE", start, end, funds=False)


@pytest.fixture
def fake_prices(monkeypatch: pytest.MonkeyPatch) -> FakePriceSource:
    fake = FakePriceSource()
    monkeypatch.setattr(price_source, "amfi_rows", fake.amfi_rows)
    monkeypatch.setattr(price_source, "nse_rows", fake.nse_rows)
    monkeypatch.setattr(price_source, "amfi_history_rows", fake.amfi_history_rows)
    monkeypatch.setattr(price_source, "nse_history_rows", fake.nse_history_rows)
    return fake


def row(
    isin: str, name: str, kind: str, price: str, day: date
) -> price_source.PriceRow:
    return price_source.PriceRow(
        isin=isin, name=name, kind=Instrument.Kind(kind), price=Decimal(price), date=day
    )


def instrument_url(isin: str) -> str:
    return reverse("instrument_detail", args=[Instrument.objects.get(isin=isin).pk])


def instrument_page(client: Client, isin: str) -> str:
    response = client.get(instrument_url(isin))
    assert response.status_code == 200
    return page_text(response.content.decode())


def make_broker(
    name: str = "Zerodha", opening: str = "0", opened: date = date(2026, 1, 1)
) -> Account:
    return Account.objects.create(
        name=name,
        kind="asset",
        investment_mode="holds_cash",
        opening_balance=Decimal(opening),
        opening_balance_date=opened,
    )


def make_direct(
    pays_from: Account,
    pays_into: Account | None = None,
    *,
    name: str = "Kuvera",
    opening: str = "0",
    opened: date = date(2026, 1, 1),
) -> Account:
    return Account.objects.create(
        name=name,
        kind="asset",
        investment_mode="direct",
        invests_from=pays_from,
        invests_into=pays_into or pays_from,
        opening_balance=Decimal(opening),
        opening_balance_date=opened,
    )


def add_price(isin: str, day: date, price: str) -> Price:
    return Price.objects.create(
        instrument=Instrument.objects.get(isin=isin), date=day, price=Decimal(price)
    )


def event_data(kind: str, isin: str, **fields: str) -> dict[str, str]:
    return {"kind": kind, "isin": isin, "date": "2026-03-01", "charges": "0"} | fields


def record_event(
    client: Client,
    account: Account,
    kind: str,
    isin: str,
    *,
    expect: int = 302,
    **fields: str,
) -> Response:
    response = client.post(
        reverse("investment_event_create", args=[account.pk]),
        event_data(kind, isin, **fields),
    )
    assert response.status_code == expect
    return response


def holdings_text(client: Client, account: Account) -> str:
    response = client.get(reverse("account_holdings", args=[account.pk]))
    assert response.status_code == 200
    return page_text(response.content.decode())


IMPORT_HEADER = (
    "date,account,isin,instrument_name,type,units,price,amount,charges,new_isin,"
    "ref,note"
)
IMPORT_DEFAULTS = {"date": "2026-03-02", "account": "Zerodha", "isin": "INF000000001"}


def import_line(kind: str, **fields: str) -> str:
    """One Investment Import row; columns not given are blank."""
    values = IMPORT_DEFAULTS | fields | {"type": kind}
    return ",".join(values.get(name, "") for name in IMPORT_HEADER.split(","))


def import_text(*lines: str) -> str:
    return "\n".join([IMPORT_HEADER, *lines]) + "\n"


def upload_import(client: Client, content: bytes) -> str:
    file = SimpleUploadedFile("events.csv", content, "text/csv")
    response = client.post(reverse("investment_import"), {"file": file})
    assert response.status_code == 200
    return page_text(response.content.decode())


def import_preview(client: Client, *lines: str) -> str:
    return upload_import(client, import_text(*lines).encode())


def import_confirm(client: Client, *lines: str) -> Response:
    return client.post(
        reverse("investment_import_confirm"), {"text": import_text(*lines)}
    )


def imported(client: Client, *lines: str) -> None:
    page = import_preview(client, *lines)
    assert "Confirm import" in page, page
    assert import_confirm(client, *lines).status_code == 302
