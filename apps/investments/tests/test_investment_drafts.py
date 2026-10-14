from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.tests.conftest import list_text, make_account
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_net_worth import home_text
from apps.investments.drafts import save_investment
from apps.investments.models import DraftInvestment, Instrument, InvestmentEvent
from apps.investments.tests.conftest import holdings_text, make_broker, make_direct
from apps.quick_add.models import Draft
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000010"


@pytest.fixture
def fund() -> Instrument:
    return Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


@pytest.fixture
def bank() -> Account:
    return opening("HDFC", "asset", "50000")


@pytest.fixture
def kuvera(bank: Account) -> Account:
    return make_direct(bank)


def investment_draft(
    account: Account, kind: str, income: Account | None = None, **detail: Any
) -> Draft:
    draft = Draft.objects.create(
        source=Draft.Source.INVESTMENT_IMPORT, date=date(2026, 3, 1)
    )
    save_investment(
        DraftInvestment(
            draft=draft,
            account=account,
            instrument=Instrument.objects.get(isin=FUND),
            kind=kind,
            **{
                name: None if value is None else Decimal(value)
                for name, value in detail.items()
            },
        ),
        income,
    )
    return draft


def buy_draft(account: Account, **detail: Any) -> Draft:
    parts = {"units": "10", "amount": "1000", "charges": "5"}
    return investment_draft(account, "buy", **(parts | detail))


def post(client: Client, draft: Draft) -> None:
    response = client.post(reverse("draft_post", args=[draft.pk]))
    assert response.status_code == 302
    draft.refresh_from_db()


def splits(transaction: Transaction | None) -> list[tuple[str, str, Decimal]]:
    return [
        (str(split.from_account), str(split.to_account), split.amount)
        for split in Split.objects.filter(transaction=transaction)
    ]


@pytest.mark.usefixtures("fund")
def test_posting_a_buy_draft_records_the_transaction_and_the_buy(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera)

    post(signed_in, draft)

    assert draft.status == Draft.Status.POSTED
    event = InvestmentEvent.objects.get()
    assert (event.kind, event.date, event.units, event.amount) == (
        "buy",
        date(2026, 3, 1),
        Decimal("10.000000"),
        Decimal("1000.00"),
    )
    assert event.charges == Decimal("5.00")
    assert event.transaction == draft.transaction
    assert splits(Transaction.objects.get()) == [("HDFC", "Kuvera", Decimal("1005.00"))]


@pytest.mark.usefixtures("fund")
@pytest.mark.parametrize(
    ("gap", "reason"),
    [("units", "Missing units."), ("amount", "Split 1: missing amount.")],
)
def test_posting_is_refused_while_units_or_amount_are_missing(
    signed_in: Client, kuvera: Account, gap: str, reason: str
) -> None:
    draft = buy_draft(kuvera, **{gap: None})

    post(signed_in, draft)

    assert draft.status == Draft.Status.WAITING
    assert draft.posting_error == reason
    assert not Transaction.objects.exists()
    assert not InvestmentEvent.objects.exists()


@pytest.mark.usefixtures("fund")
def test_rejecting_records_neither_the_transaction_nor_the_buy(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera)

    response = signed_in.post(reverse("draft_reject", args=[draft.pk]))

    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.status == Draft.Status.REJECTED
    assert not Transaction.objects.exists()
    assert not InvestmentEvent.objects.exists()


@pytest.mark.usefixtures("fund")
def test_a_waiting_draft_changes_no_lots_cash_balance_or_net_worth(
    signed_in: Client, bank: Account
) -> None:
    broker = make_broker(opening="10000")
    kuvera = make_direct(bank)

    buy_draft(kuvera)
    investment_draft(broker, "dividend", amount="250")

    assert "Market Value ₹10,000.00 Cash ₹10,000.00 Cost Basis ₹0.00" in (
        holdings_text(signed_in, broker)
    )
    assert "Nothing held yet." in holdings_text(signed_in, kuvera)
    assert "Net Worth ₹60,000.00" in home_text(signed_in)
    assert "Balance ₹50,000.00" in list_text(signed_in, "asset")


@pytest.mark.usefixtures("fund")
def test_posting_a_sell_draft_pays_its_net_proceeds_into_pays_into(
    signed_in: Client, bank: Account
) -> None:
    savings = opening("SBI", "asset", "0")
    kuvera = make_direct(bank, savings)
    post(signed_in, buy_draft(kuvera))
    draft = investment_draft(kuvera, "sell", units="4", amount="480", charges="2")

    post(signed_in, draft)

    event = InvestmentEvent.objects.get(kind="sell")
    assert event.transaction == draft.transaction
    assert splits(event.transaction) == [("Kuvera", "SBI", Decimal("478.00"))]


@pytest.mark.usefixtures("fund")
def test_a_sell_draft_of_more_units_than_held_is_refused(
    signed_in: Client, kuvera: Account
) -> None:
    draft = investment_draft(kuvera, "sell", units="4", amount="480")

    post(signed_in, draft)

    assert draft.status == Draft.Status.WAITING
    assert draft.posting_error == "Only 0 units of Nifty Fund were held on 1 Mar 2026."


@pytest.mark.usefixtures("fund")
def test_posting_a_dividend_draft_records_income_and_the_dividend(
    signed_in: Client,
) -> None:
    broker = make_broker()
    dividends = make_account("Dividends", "income")
    draft = investment_draft(broker, "dividend", income=dividends, amount="250")

    post(signed_in, draft)

    event = InvestmentEvent.objects.get()
    assert (event.kind, event.amount) == ("dividend", Decimal("250.00"))
    assert splits(draft.transaction) == [("Dividends", "Zerodha", Decimal("250.00"))]


@pytest.mark.usefixtures("fund")
def test_a_dividend_draft_needs_its_income_account(
    signed_in: Client,
) -> None:
    draft = investment_draft(make_broker(), "dividend", amount="250")

    post(signed_in, draft)

    assert draft.posting_error == "Split 1: missing From Account."


@pytest.mark.usefixtures("fund")
def test_a_draft_dated_inside_the_opening_balance_is_refused(
    signed_in: Client, bank: Account
) -> None:
    kuvera = make_direct(bank, opened=date(2026, 6, 1))
    draft = buy_draft(kuvera)

    post(signed_in, draft)

    assert draft.posting_error == (
        "It is dated on or before Kuvera's Opening Balance date; "
        "record it on its Holdings tab instead."
    )


@pytest.mark.usefixtures("fund")
def test_posting_a_buy_draft_queues_a_price_backfill(
    signed_in: Client, kuvera: Account
) -> None:
    post(signed_in, buy_draft(kuvera))

    assert ProcrastinateJob.objects.get().task_name == "investments.backfill_prices"


@pytest.mark.usefixtures("fund")
def test_posting_a_dividend_draft_queues_no_backfill(signed_in: Client) -> None:
    dividends = make_account("Dividends", "income")
    draft = investment_draft(make_broker(), "dividend", income=dividends, amount="9")

    post(signed_in, draft)

    assert draft.status == Draft.Status.POSTED
    assert not ProcrastinateJob.objects.exists()
