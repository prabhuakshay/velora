from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import (
    event_data,
    holdings_text,
    make_broker,
    record_event,
)
from apps.investments.tests.test_investment_events import account_text

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000001"


@pytest.fixture(autouse=True)
def _instrument() -> None:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")


@pytest.fixture
def dividends() -> Account:
    return make_account("Dividends", "income")


def record_dividend(
    client: Client,
    broker: Account,
    income: Account,
    amount: str,
    day: str = "2026-03-01",
) -> None:
    record_event(
        client,
        broker,
        "dividend",
        FUND,
        amount=amount,
        income_account=str(income.pk),
        date=day,
    )


def test_a_dividend_posts_income_into_an_account_that_holds_cash(
    signed_in: Client, dividends: Account
) -> None:
    broker = make_broker(opening="10000")
    record_event(signed_in, broker, "buy", FUND, units="10", amount="1000")

    record_dividend(signed_in, broker, dividends, "250")

    page = account_text(signed_in, broker)
    assert "Balance ₹10,250.00" in page
    assert "Cash ₹9,250.00" in page
    assert "Dividend from Nifty Fund" in page
    assert "Dividend from Nifty Fund" in account_text(signed_in, dividends)
    assert "Nifty Fund 10 ₹1,000.00 ₹1,000.00 ₹0.00 ₹0.00 ₹250.00" in (
        holdings_text(signed_in, broker)
    )


def test_a_dividend_on_or_before_the_opening_date_builds_history_only(
    signed_in: Client, dividends: Account
) -> None:
    broker = make_broker(opening="5000", opened=date(2026, 2, 1))

    record_dividend(signed_in, broker, dividends, "80", "2026-02-01")

    page = account_text(signed_in, broker)
    assert "Balance ₹5,000.00" in page
    assert "No Transactions yet" in page
    assert "₹80.00" in holdings_text(signed_in, broker)


def test_editing_a_dividend_changes_its_transaction(
    signed_in: Client, dividends: Account
) -> None:
    broker = make_broker(opening="5000")
    record_dividend(signed_in, broker, dividends, "80")
    event = InvestmentEvent.objects.get()

    response = signed_in.post(
        reverse("investment_event_edit", args=[event.pk]),
        event_data("dividend", FUND, amount="95", income_account=str(dividends.pk)),
    )

    assert response.status_code == 302
    page = account_text(signed_in, broker)
    assert "Balance ₹5,095.00" in page
    assert page.count("Dividend from Nifty Fund") == 1


def test_editing_a_dividend_starts_from_its_income_account(
    signed_in: Client, dividends: Account
) -> None:
    broker = make_broker(opening="5000")
    record_dividend(signed_in, broker, dividends, "80")
    event = InvestmentEvent.objects.get()

    response = signed_in.get(reverse("investment_event_edit", args=[event.pk]))

    assert response.context["form"]["income_account"].value() == dividends.pk


def test_editing_a_dividend_to_before_the_opening_date_removes_its_transaction(
    signed_in: Client, dividends: Account
) -> None:
    broker = make_broker(opening="5000", opened=date(2026, 2, 1))
    record_dividend(signed_in, broker, dividends, "80")
    event = InvestmentEvent.objects.get()

    signed_in.post(
        reverse("investment_event_edit", args=[event.pk]),
        event_data(
            "dividend",
            FUND,
            amount="80",
            income_account=str(dividends.pk),
            date="2026-01-15",
        ),
    )

    assert "No Transactions yet" in account_text(signed_in, broker)


def test_deleting_a_dividend_deletes_its_transaction(
    signed_in: Client, dividends: Account
) -> None:
    broker = make_broker(opening="5000")
    record_dividend(signed_in, broker, dividends, "80")
    event = InvestmentEvent.objects.get()

    response = signed_in.post(reverse("investment_event_delete", args=[event.pk]))

    assert response.status_code == 302
    page = account_text(signed_in, broker)
    assert "Balance ₹5,000.00" in page
    assert "No Transactions yet" in page


def test_a_dividend_needs_an_amount_and_an_income_account(signed_in: Client) -> None:
    broker = make_broker(opening="5000")

    response = record_event(signed_in, broker, "dividend", FUND, expect=200)

    assert response.context["form"].errors == {
        "amount": ["This field is required."],
        "income_account": ["This field is required."],
    }
    assert not InvestmentEvent.objects.exists()
