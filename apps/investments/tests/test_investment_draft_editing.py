from decimal import Decimal
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account, page_text
from apps.investments.models import InvestmentEvent
from apps.investments.tests.conftest import make_broker
from apps.investments.tests.test_investment_drafts import (
    bank,
    buy_draft,
    fund,
    investment_draft,
    kuvera,
    post,
    splits,
)
from apps.quick_add.models import Draft

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

__all__ = ["bank", "fund", "kuvera"]


def text_of(html: str) -> str:
    return unescape(page_text(html))


def drafts_text(client: Client) -> str:
    response = client.get(reverse("draft_list"))
    assert response.status_code == 200
    return text_of(response.content.decode())


def edit_url(draft: Draft) -> str:
    return reverse("draft_edit", args=[draft.pk])


def edit_data(**fields: str) -> dict[str, str]:
    return {
        "date": "2026-03-01",
        "description": "",
        "units": "10",
        "amount": "1000",
        "charges": "5",
    } | fields


@pytest.mark.usefixtures("fund")
def test_the_draft_shows_its_investment_event_and_where_it_came_from(
    signed_in: Client, kuvera: Account
) -> None:
    buy_draft(kuvera, units=None)

    page = drafts_text(signed_in)

    assert "Investment Import" in page
    assert "Buy Nifty Fund in Kuvera · Units needed" in page
    assert "₹1,005.00" in page
    assert "HDFC Kuvera" in page


@pytest.mark.usefixtures("fund")
def test_a_complete_draft_shows_its_units_and_price(
    signed_in: Client, kuvera: Account
) -> None:
    buy_draft(kuvera)

    assert "Buy Nifty Fund in Kuvera · 10 units at ₹100.0000" in drafts_text(signed_in)


@pytest.mark.usefixtures("fund")
def test_editing_saves_the_draft_waiting_with_gaps(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera)

    response = signed_in.post(
        edit_url(draft), edit_data(units="", amount="1200", description="SIP")
    )

    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.status == Draft.Status.WAITING
    assert (draft.description, draft.investment.units) == ("SIP", None)
    assert draft.amount == Decimal("1205.00")
    page = text_of(signed_in.get(edit_url(draft)).content.decode())
    assert "Can't post yet: Missing units." in page
    assert not InvestmentEvent.objects.exists()


@pytest.mark.usefixtures("fund")
def test_editing_and_posting_records_the_edited_buy(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera, units=None)

    response = signed_in.post(edit_url(draft), edit_data(units="9.8765", action="post"))

    assert response.status_code == 302
    event = InvestmentEvent.objects.get()
    assert event.units == Decimal("9.876500")
    draft.refresh_from_db()
    assert event.transaction == draft.transaction


@pytest.mark.usefixtures("fund")
def test_posting_an_edit_that_is_refused_keeps_it_waiting_and_says_why(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera)

    response = signed_in.post(edit_url(draft), edit_data(units="", action="post"))

    assert response.status_code == 200
    assert "Couldn't post: Missing units." in text_of(response.content.decode())
    draft.refresh_from_db()
    assert draft.status == Draft.Status.WAITING
    assert not InvestmentEvent.objects.exists()


@pytest.mark.usefixtures("fund")
def test_editing_a_dividend_draft_picks_its_income_account(
    signed_in: Client,
) -> None:
    broker = make_broker()
    dividends = make_account("Dividends", "income")
    draft = investment_draft(broker, "dividend", amount="250")

    response = signed_in.post(
        edit_url(draft),
        {
            "date": "2026-03-01",
            "amount": "300",
            "income_account": str(dividends.pk),
            "action": "post",
        },
    )

    assert response.status_code == 302
    draft.refresh_from_db()
    assert splits(draft.transaction) == [("Dividends", "Zerodha", Decimal("300.00"))]


@pytest.mark.usefixtures("fund")
def test_an_invalid_edit_is_shown_again(signed_in: Client, kuvera: Account) -> None:
    draft = buy_draft(kuvera)

    response = signed_in.post(edit_url(draft), edit_data(charges="-1"))

    assert response.status_code == 200
    assert "Charges can't be negative." in text_of(response.content.decode())


@pytest.mark.usefixtures("fund")
def test_editing_a_draft_posted_meanwhile_saves_nothing(
    signed_in: Client, kuvera: Account
) -> None:
    draft = buy_draft(kuvera)
    post(signed_in, draft)

    response = signed_in.post(edit_url(draft), edit_data(units="3"), follow=True)

    assert "already posted or rejected" in text_of(response.content.decode())
    assert InvestmentEvent.objects.get().units == Decimal("10.000000")
