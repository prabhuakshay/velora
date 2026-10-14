from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.test_balance import opening
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import event_data, make_direct, record_event
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

FUND = "INF000000001"


@pytest.fixture
def bought(signed_in: Client) -> InvestmentEvent:
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    account = make_direct(opening("HDFC", "asset", "5000"))
    record_event(signed_in, account, "buy", FUND, units="10", amount="1000")
    return InvestmentEvent.objects.get()


def linked(event: InvestmentEvent) -> Transaction:
    assert event.transaction is not None
    return event.transaction


def holdings_url(event: InvestmentEvent) -> str:
    return reverse("account_holdings", args=[event.account_id])


def test_a_linked_transaction_cant_be_edited(
    signed_in: Client, bought: InvestmentEvent
) -> None:
    transaction = linked(bought)
    split = transaction.splits.get()

    response = signed_in.post(
        reverse("transaction_edit", args=[transaction.pk]),
        form_data(split.from_account, bought.account, "5", split_id=split.pk),
        follow=True,
    )

    assert response.redirect_chain[-1][0] == holdings_url(bought)
    assert "change it on Kuvera&#x27;s Holdings" in response.content.decode()
    assert transaction.splits.get().amount == Decimal(1000)


def test_a_linked_transaction_cant_be_deleted(
    signed_in: Client, bought: InvestmentEvent
) -> None:
    transaction = linked(bought)

    for method in (signed_in.get, signed_in.post):
        response = method(reverse("transaction_delete", args=[transaction.pk]))
        assert response.status_code == 302
        assert response["Location"] == holdings_url(bought)

    assert Transaction.objects.filter(pk=transaction.pk).exists()


def test_a_linked_transaction_links_to_its_holdings_instead_of_edit(
    signed_in: Client, bought: InvestmentEvent
) -> None:
    transaction = linked(bought)

    page = signed_in.get(
        reverse("transaction_detail", args=[transaction.pk])
    ).content.decode()

    assert holdings_url(bought) in page
    assert reverse("transaction_delete", args=[transaction.pk]) not in page


def test_the_event_itself_can_still_be_edited(
    signed_in: Client, bought: InvestmentEvent
) -> None:
    response = signed_in.post(
        reverse("investment_event_edit", args=[bought.pk]),
        event_data("buy", FUND, units="10", amount="1200"),
    )

    assert response.status_code == 302
    assert linked(InvestmentEvent.objects.get()).splits.get().amount == Decimal(1200)


def test_the_event_itself_can_still_be_deleted(
    signed_in: Client, bought: InvestmentEvent
) -> None:
    transaction = linked(bought)

    signed_in.post(reverse("investment_event_delete", args=[bought.pk]))

    assert not Transaction.objects.filter(pk=transaction.pk).exists()
