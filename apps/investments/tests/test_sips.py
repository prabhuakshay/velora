from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.investments.models import InvestmentEvent
from apps.investments.tests.conftest import add_price
from apps.investments.tests.test_investment_draft_editing import (
    drafts_text,
    text_of as page_text,
)
from apps.investments.tests.test_investment_drafts import (
    FUND,
    bank,
    fund,
    kuvera,
    splits,
)
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Occurrence, Schedule
from apps.schedules.tests.conftest import make_schedule, schedule_form_data

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.investments.models import Instrument

pytestmark = pytest.mark.django_db

__all__ = ["bank", "fund", "kuvera"]


def sip_form_data(
    account: Account, amount: str = "5000", **fields: str
) -> dict[str, Any]:
    assert account.invests_from is not None
    return schedule_form_data(
        (account.invests_from, account, "5000"),
        description="Nifty SIP",
        is_sip="on",
        sip_account=account.pk,
        sip_isin=FUND,
        **fields,
    )


def test_a_schedule_is_marked_as_a_sip_with_its_instrument_and_account(
    signed_in: Client, kuvera: Account, fund: Instrument
) -> None:
    response = signed_in.post(reverse("schedule_create"), sip_form_data(kuvera))

    assert response.status_code == 302
    schedule = Schedule.objects.get()
    assert (schedule.is_sip, schedule.sip_account, schedule.sip_instrument) == (
        True,
        kuvera,
        fund,
    )


@pytest.mark.usefixtures("fund")
def test_a_sip_shows_its_instrument_and_can_be_unmarked(
    signed_in: Client, kuvera: Account
) -> None:
    signed_in.post(reverse("schedule_create"), sip_form_data(kuvera))
    schedule = Schedule.objects.get()
    detail = signed_in.get(reverse("schedule_detail", args=[schedule.pk]))
    assert "SIP · Nifty Fund" in page_text(detail.content.decode())
    edit = signed_in.get(reverse("schedule_edit", args=[schedule.pk]))
    assert f'value="{FUND}"' in edit.content.decode()

    data = sip_form_data(kuvera) | {"is_sip": ""}
    signed_in.post(reverse("schedule_edit", args=[schedule.pk]), data)

    schedule.refresh_from_db()
    assert (schedule.is_sip, schedule.sip_instrument) == (False, None)


@pytest.mark.usefixtures("fund")
@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"sip_isin": "INF999999999"}, "Velora doesn't know this ISIN."),
        ({"sip_account": ""}, "Pick the Investment Account it buys in."),
    ],
)
def test_a_sip_needs_a_known_instrument_and_its_investment_account(
    signed_in: Client, kuvera: Account, fields: dict[str, str], reason: str
) -> None:
    response = signed_in.post(
        reverse("schedule_create"), sip_form_data(kuvera) | fields
    )

    assert response.status_code == 200
    assert reason in page_text(response.content.decode())
    assert not Schedule.objects.exists()


@pytest.mark.usefixtures("fund")
def test_a_sip_pays_its_investment_account_from_its_pays_from_account(
    signed_in: Client, kuvera: Account, bank: Account
) -> None:
    savings = make_account("Savings", "asset")
    data = schedule_form_data(
        (bank, savings, "5000"), is_sip="on", sip_account=kuvera.pk, sip_isin=FUND
    )

    response = signed_in.post(reverse("schedule_create"), data)

    assert response.status_code == 200
    assert "A SIP has one Split, from HDFC into Kuvera." in page_text(
        response.content.decode()
    )
    assert not Schedule.objects.exists()


def make_sip(account: Account, instrument: Instrument, **fields: object) -> None:
    assert account.invests_from is not None
    make_schedule(
        (account.invests_from, account, "5000"),
        description="Monthly Nifty",
        sip_account=account,
        sip_instrument=instrument,
        **fields,
    )


def test_on_its_due_date_a_sip_drafts_a_buy_at_that_days_price(
    signed_in: Client, kuvera: Account, fund: Instrument
) -> None:
    make_sip(kuvera, fund)
    add_price(FUND, date(2026, 10, 4), "100")
    add_price(FUND, date(2026, 10, 5), "125")

    run_daily_job(date(2026, 10, 5))

    page = drafts_text(signed_in)
    assert "SIP" in page
    assert "Buy Nifty Fund in Kuvera · 40 units at ₹125.0000" in page


def test_with_no_price_yet_the_draft_waits_and_fills_units_once_one_arrives(
    signed_in: Client, kuvera: Account, fund: Instrument
) -> None:
    make_sip(kuvera, fund)
    add_price(FUND, date(2026, 10, 2), "100")
    run_daily_job(date(2026, 10, 5))
    assert "Buy Nifty Fund in Kuvera · Units needed" in drafts_text(signed_in)

    add_price(FUND, date(2026, 10, 6), "200")
    run_daily_job(date(2026, 10, 6))
    run_daily_job(date(2026, 10, 6))

    assert "Buy Nifty Fund in Kuvera · 25 units at ₹200.0000" in drafts_text(signed_in)
    assert Draft.objects.get().amount == Decimal("5000.00")


def test_edited_units_are_posted_and_the_occurrence_is_paid(
    signed_in: Client, kuvera: Account, fund: Instrument
) -> None:
    make_sip(kuvera, fund)
    add_price(FUND, date(2026, 10, 5), "125")
    run_daily_job(date(2026, 10, 5))
    draft = Draft.objects.get()

    response = signed_in.post(
        reverse("draft_edit", args=[draft.pk]),
        {
            "date": "2026-10-05",
            "description": "Monthly Nifty",
            "units": "39.987",
            "amount": "5000",
            "charges": "0",
            "action": "post",
        },
    )

    assert response.status_code == 302
    event = InvestmentEvent.objects.get()
    assert (event.kind, event.units, event.amount) == (
        "buy",
        Decimal("39.987000"),
        Decimal("5000.00"),
    )
    occurrence = Occurrence.objects.get(due_date=date(2026, 10, 5))
    assert occurrence.status == Occurrence.Status.PAID
    assert occurrence.transaction == event.transaction
    assert splits(event.transaction) == [("HDFC", "Kuvera", Decimal("5000.00"))]


@pytest.mark.parametrize("priced_on", [date(2026, 10, 5), date(2026, 10, 7)])
def test_an_auto_post_sip_posts_its_buy_once_it_is_priced(
    kuvera: Account, fund: Instrument, priced_on: date
) -> None:
    make_sip(kuvera, fund, auto_post=True)

    for day in (5, 6, 7):
        if day == priced_on.day:
            add_price(FUND, priced_on, "125")
        run_daily_job(date(2026, 10, day))

    event = InvestmentEvent.objects.get()
    assert (event.date, event.units) == (date(2026, 10, 5), Decimal("40.000000"))
    draft = Draft.objects.get()
    assert (draft.status, draft.posting_error) == (Draft.Status.POSTED, "")
    occurrence = Occurrence.objects.get(due_date=date(2026, 10, 5))
    assert occurrence.status == Occurrence.Status.PAID


def test_an_auto_post_sip_priced_after_its_grace_waits_for_the_user(
    kuvera: Account, fund: Instrument
) -> None:
    make_sip(kuvera, fund, auto_post=True, grace_days=1)

    run_daily_job(date(2026, 10, 5))
    add_price(FUND, date(2026, 10, 9), "125")
    run_daily_job(date(2026, 10, 9))

    draft = Draft.objects.get()
    assert (draft.status, draft.investment.units) == (
        Draft.Status.WAITING,
        Decimal("40.000000"),
    )
    assert not InvestmentEvent.objects.exists()
