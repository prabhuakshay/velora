from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import event_data, make_direct, record_event
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

FUND = "INF000000010"


@pytest.fixture(autouse=True)
def _fund() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


def direct_data(**fields: object) -> dict[str, object]:
    return {
        "name": "Kuvera",
        "opening_balance": "0",
        "opening_balance_date": "2026-01-01",
        "investment_mode": "direct",
    } | fields


def account_text(client: Client, account: Account) -> str:
    return page_text(
        client.get(account_url("account_transactions", account)).content.decode()
    )


def post_event(
    client: Client, account: Account, kind: str, fields: dict[str, str]
) -> None:
    response = client.post(
        reverse("investment_event_create", args=[account.pk]),
        event_data(kind, FUND, **fields),
    )
    assert response.status_code == 302


def buy(client: Client, account: Account, **fields: str) -> None:
    post_event(
        client,
        account,
        "buy",
        {"units": "10", "amount": "1000"} | fields,
    )


def edit(client: Client, event: InvestmentEvent, kind: str, **fields: str) -> None:
    response = client.post(
        reverse("investment_event_edit", args=[event.pk]),
        event_data(kind, FUND, **fields),
    )
    assert response.status_code == 302


def test_a_direct_account_pays_from_and_into_asset_accounts(
    signed_in: Client,
) -> None:
    bank = opening("HDFC", "asset", "0")
    savings = opening("SBI", "asset", "0")

    response = signed_in.post(
        reverse("account_create", args=["asset"]),
        direct_data(invests_from=bank.pk, invests_into=savings.pk),
    )

    assert response.status_code == 302
    page = account_text(signed_in, Account.objects.get(name="Kuvera"))
    assert "Investment Account · Direct" in page
    assert "Pays from HDFC" in page
    assert "Pays into SBI" in page


def test_a_direct_account_needs_pays_from_and_pays_into(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "0")

    response = signed_in.post(
        reverse("account_create", args=["asset"]), direct_data(invests_from=bank.pk)
    )

    assert response.status_code == 200
    assert "A Direct Investment Account needs a Pays from and a Pays into" in (
        page_text(response.content.decode())
    )
    assert not Account.objects.filter(name="Kuvera").exists()


def test_only_a_direct_account_keeps_pays_from_and_pays_into(
    signed_in: Client,
) -> None:
    bank = opening("HDFC", "asset", "0")

    signed_in.post(
        reverse("account_create", args=["asset"]),
        direct_data(
            investment_mode="holds_cash", invests_from=bank.pk, invests_into=bank.pk
        ),
    )

    broker = Account.objects.get(name="Kuvera")
    assert broker.invests_from is None
    assert broker.invests_into is None


def test_a_buy_is_paid_from_pays_from(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "10000")
    kuvera = make_direct(bank)

    buy(signed_in, kuvera, charges="15")

    assert "Balance ₹8,985.00" in account_text(signed_in, bank)
    page = account_text(signed_in, kuvera)
    assert "Balance ₹1,015.00" in page
    assert "Cash ₹0.00" in page
    assert "Buy Nifty Fund" in page


def test_a_sell_pays_its_net_proceeds_into_pays_into(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "10000")
    savings = opening("SBI", "asset", "0")
    kuvera = make_direct(bank, savings)
    buy(signed_in, kuvera)

    record_event(
        signed_in,
        kuvera,
        "sell",
        FUND,
        units="4",
        amount="480",
        charges="5",
        date="2026-03-02",
    )

    assert "Balance ₹9,000.00" in account_text(signed_in, bank)
    assert "Balance ₹475.00" in account_text(signed_in, savings)
    page = account_text(signed_in, kuvera)
    assert "Balance ₹525.00" in page
    assert "Cash ₹0.00" in page


def test_editing_a_buy_updates_its_transaction(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "10000")
    kuvera = make_direct(bank)
    buy(signed_in, kuvera)

    edit(
        signed_in,
        InvestmentEvent.objects.get(),
        "buy",
        units="10",
        amount="1500",
    )

    assert "Balance ₹8,500.00" in account_text(signed_in, bank)
    assert Transaction.objects.count() == 1


def test_deleting_a_buy_removes_its_transaction(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "10000")
    kuvera = make_direct(bank)
    buy(signed_in, kuvera)
    event = InvestmentEvent.objects.get()

    signed_in.post(reverse("investment_event_delete", args=[event.pk]))

    assert "Balance ₹10,000.00" in account_text(signed_in, bank)
    assert not Transaction.objects.exists()


def test_events_on_or_before_the_opening_date_post_nothing(
    signed_in: Client,
) -> None:
    bank = opening("HDFC", "asset", "10000")
    kuvera = make_direct(bank, opening="1000", opened=date(2026, 3, 1))

    buy(signed_in, kuvera, date="2026-03-01")

    assert "Balance ₹10,000.00" in account_text(signed_in, bank)
    assert "Cash ₹0.00" in account_text(signed_in, kuvera)
    assert not Transaction.objects.exists()


def test_moving_a_buy_onto_the_opening_date_removes_its_transaction(
    signed_in: Client,
) -> None:
    bank = opening("HDFC", "asset", "10000")
    kuvera = make_direct(bank, opened=date(2026, 2, 1))
    buy(signed_in, kuvera)

    edit(
        signed_in,
        InvestmentEvent.objects.get(),
        "buy",
        units="10",
        amount="1000",
        date="2026-02-01",
    )

    assert "Balance ₹10,000.00" in account_text(signed_in, bank)
    assert not Transaction.objects.exists()


def test_a_buy_its_bank_cant_pay_for_yet_is_refused(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "10000")
    bank.opening_balance_date = date(2026, 4, 1)
    bank.save()
    kuvera = make_direct(bank)

    response = record_event(
        signed_in, kuvera, "buy", FUND, expect=200, units="1", amount="1"
    )

    assert "before the Opening Balance date of HDFC" in response.content.decode()
    assert not InvestmentEvent.objects.exists()


# Each step's events, all after the Opening Balance date of 1 Jan 2026.
STEPS = (
    ("buy", {"units": "10", "amount": "1000", "charges": "15"}),
    ("buy", {"units": "5.5", "amount": "605", "date": "2026-03-03"}),
    (
        "sell",
        {
            "units": "12",
            "amount": "1440",
            "charges": "7.5",
            "date": "2026-03-04",
        },
    ),
    ("buy", {"units": "2", "amount": "180", "date": "2026-02-02"}),
    ("sell", {"units": "5.5", "amount": "522.5", "date": "2026-04-01"}),
)


def test_cash_stays_zero_through_any_mix_of_buys_and_sells(
    signed_in: Client,
) -> None:
    bank = opening("HDFC", "asset", "10000")
    kuvera = make_direct(bank, opening="0")

    for kind, fields in STEPS:
        post_event(signed_in, kuvera, kind, fields)
        assert "Cash ₹0.00" in account_text(signed_in, kuvera)

    first_buy = InvestmentEvent.objects.filter(kind="buy").earliest("date", "pk")
    edit(signed_in, first_buy, "buy", units="10", amount="800", charges="3")
    assert "Cash ₹0.00" in account_text(signed_in, kuvera)

    last_sell = InvestmentEvent.objects.filter(kind="sell").latest("date")
    signed_in.post(reverse("investment_event_delete", args=[last_sell.pk]))
    assert "Cash ₹0.00" in account_text(signed_in, kuvera)


def test_a_dividend_is_paid_into_pays_into(signed_in: Client) -> None:
    bank = opening("HDFC", "asset", "10000")
    savings = opening("SBI", "asset", "0")
    dividends = make_account("Dividends", "income")
    kuvera = make_direct(bank, savings)
    buy(signed_in, kuvera)

    post_event(
        signed_in,
        kuvera,
        "dividend",
        {"amount": "250", "income_account": str(dividends.pk)},
    )

    assert "Balance ₹250.00" in account_text(signed_in, savings)
    page = account_text(signed_in, kuvera)
    assert "Balance ₹1,000.00" in page
    assert "Cash ₹0.00" in page


def test_deleting_a_bank_a_direct_account_uses_sends_the_user_to_merge(
    signed_in: Client,
) -> None:
    bank = opening("HDFC", "asset", "0")
    make_direct(bank)

    response = signed_in.post(account_url("account_delete", bank))

    assert response["Location"] == account_url("account_merge", bank)
    assert Account.objects.filter(pk=bank.pk).exists()


def test_merging_a_bank_repoints_the_direct_accounts_using_it(
    signed_in: Client,
) -> None:
    old_bank = opening("Old bank", "asset", "0")
    bank = opening("Bank", "asset", "0")
    kuvera = make_direct(old_bank)

    signed_in.post(account_url("account_merge", old_bank), {"target": bank.pk})

    kuvera.refresh_from_db()
    assert (kuvera.invests_from, kuvera.invests_into) == (bank, bank)
