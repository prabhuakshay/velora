from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.investments import price_source
from apps.investments.models import Instrument

if TYPE_CHECKING:
    from datetime import date

    from django.test import Client


class FakePriceSource:
    """Stands in for the price-source client: hands back the rows it is given.

    A source set to an exception raises it instead, as a failed fetch would.
    """

    def __init__(self) -> None:
        self.amfi: list[price_source.PriceRow] | Exception = []
        self.nse: list[price_source.PriceRow] | Exception = []

    def amfi_rows(self) -> list[price_source.PriceRow]:
        if isinstance(self.amfi, Exception):
            raise self.amfi
        return self.amfi

    def nse_rows(self, day: date) -> list[price_source.PriceRow]:
        if isinstance(self.nse, Exception):
            raise self.nse
        return self.nse


@pytest.fixture
def fake_prices(monkeypatch: pytest.MonkeyPatch) -> FakePriceSource:
    fake = FakePriceSource()
    monkeypatch.setattr(price_source, "amfi_rows", fake.amfi_rows)
    monkeypatch.setattr(price_source, "nse_rows", fake.nse_rows)
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
