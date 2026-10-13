from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.accounts.tests.test_balance import opening
from apps.investments.drafts import save_investment
from apps.investments.models import DraftInvestment, Instrument, InvestmentEvent
from apps.investments.tests.conftest import (
    holdings_text,
    imported,
    make_broker,
    make_direct,
    record_event,
)
from apps.investments.tests.test_import_export import exported
from apps.quick_add.models import Draft
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
STOCK = "INE000000001"


def record_history(
    client: Client, broker: Account, kuvera: Account, dividends: Account
) -> None:
    history: tuple[tuple[Account, str, str, dict[str, Any]], ...] = (
        (broker, "buy", FUND, {"units": "10", "price": "100", "amount": "1000"}),
        (kuvera, "buy", STOCK, {"units": "4", "price": "250", "amount": "1000",
                                "charges": "2.5"}),
        (kuvera, "sell", STOCK, {"date": "2026-03-05", "units": "1",
                                 "price": "300", "amount": "300", "charges": "1"}),
        (broker, "dividend", FUND, {"date": "2026-03-10", "amount": "40",
                                    "income_account": str(dividends.pk)}),
        (kuvera, "dividend", STOCK, {"date": "2026-03-11", "amount": "12",
                                     "income_account": str(dividends.pk)}),
        (broker, "bonus", FUND, {"date": "2026-03-12", "units": "2"}),
    )  # fmt: skip
    for account, kind, isin, fields in history:
        record_event(client, account, kind, isin, **fields)


def start_empty() -> None:
    """Velora with only the Accounts: no events, Transactions or Instruments."""
    InvestmentEvent.objects.all().delete()
    Transaction.objects.all().delete()
    Instrument.objects.all().delete()


def holdings(client: Client, *accounts: Account) -> list[str]:
    client.get(reverse("draft_list"))  # shows, so clears, any messages
    return [holdings_text(client, account) for account in accounts]


def post_every_draft(client: Client, dividends: Account) -> None:
    for detail in DraftInvestment.objects.filter(kind=DraftInvestment.Kind.DIVIDEND):
        save_investment(detail, dividends)
    response = client.post(reverse("draft_post_all"))
    assert response.status_code == 302
    assert not Draft.objects.filter(status=Draft.Status.WAITING).exists()


def test_export_import_and_posting_drafts_gives_back_the_same_portfolio(
    signed_in: Client,
) -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=STOCK, name="Acme Ltd", kind="stock")
    bank = opening("Bank", "asset", "10000")
    broker = make_broker(opening="5000", opened=date(2026, 1, 1))
    kuvera = make_direct(bank, opened=date(2026, 1, 1))
    dividends = make_account("Dividends", "income")
    record_history(signed_in, broker, kuvera, dividends)
    first = exported(signed_in)
    pages = holdings(signed_in, broker, kuvera)
    start_empty()

    imported(signed_in, *first.decode().splitlines()[1:])
    post_every_draft(signed_in, dividends)

    assert exported(signed_in) == first
    assert holdings(signed_in, broker, kuvera) == pages
    assert InvestmentEvent.objects.filter(transaction__isnull=False).count() == 4
