from datetime import date
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.test_balance import opening
from apps.goals.tests.conftest import (
    allocate,
    create_goal,
    goal_text,
    goals_text,
    source,
)
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.goals.models import Goal

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    today = date(2026, 10, 13)
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: today)


@pytest.fixture
def savings() -> Account:
    return opening("Savings", "asset", "100000")


@pytest.fixture
def bank() -> Account:
    return opening("Bank", "asset", "500000")


def saving_for(
    client: Client,
    savings: Account,
    target: str,
    target_date: str,
    **fields: Any,
) -> Goal:
    """A Goal with all of Savings allocated to it, by default not inflated or grown."""
    goal = create_goal(
        client,
        "House",
        target,
        target_date,
        **{"inflation": "0", "expected_return": "0"} | fields,
    )
    assert goal is not None
    allocate(client, goal, source(savings), percent="100")
    return goal


def test_a_goal_starts_at_six_percent_inflation_and_twelve_percent_return(
    signed_in: Client,
) -> None:
    form = signed_in.get(reverse("goal_create")).content.decode()

    assert 'name="inflation" value="6"' in form
    assert 'name="expected_return" value="12"' in form


def test_a_goal_page_shows_its_assumptions_and_inflated_target(
    signed_in: Client, savings: Account
) -> None:
    goal = saving_for(
        signed_in,
        savings,
        "100000",
        "2028-10-13",
        inflation="6",
        expected_return="12",
    )

    page = goal_text(signed_in, goal)

    assert "6% inflation" in page
    assert "12% expected return" in page
    assert "Inflated target ₹1,12,360.00" in page
    assert "Projection ₹1,25,440.00" in page


def test_an_on_track_goal_needs_no_monthly_investment(
    signed_in: Client, savings: Account
) -> None:
    goal = saving_for(signed_in, savings, "100000", "2028-10-13")

    page = goal_text(signed_in, goal)

    assert "On track" in page
    assert "Required Monthly Investment ₹0.00" in page


def test_a_behind_goal_shows_the_gap_and_what_to_add_each_month(
    signed_in: Client, savings: Account
) -> None:
    goal = saving_for(signed_in, savings, "1000000", "2027-10-13")

    page = goal_text(signed_in, goal)

    assert "Behind by ₹9,00,000.00" in page
    assert "Required Monthly Investment ₹75,000.00" in page


def test_a_linked_schedule_counts_toward_the_projection(
    signed_in: Client, savings: Account, bank: Account
) -> None:
    sip = make_schedule((bank, savings, "25000"), description="House SIP")
    goal = saving_for(signed_in, savings, "1000000", "2027-10-13", schedules=[sip.pk])

    page = goal_text(signed_in, goal)

    assert "House SIP" in page
    assert "Projection ₹4,00,000.00" in page
    assert "Behind by ₹6,00,000.00" in page
    assert "Required Monthly Investment ₹50,000.00" in page


def test_a_schedule_ending_before_the_target_date_counts_until_its_end(
    signed_in: Client, savings: Account, bank: Account
) -> None:
    sip = make_schedule((bank, savings, "25000"), ends_on=date(2027, 4, 13))
    goal = saving_for(signed_in, savings, "1000000", "2027-10-13", schedules=[sip.pk])

    assert "Projection ₹2,50,000.00" in goal_text(signed_in, goal)


def test_a_schedule_ending_after_some_payments_counts_those_left(
    signed_in: Client, savings: Account, bank: Account
) -> None:
    # Six from 5 Oct 2026: November to March are still to come.
    sip = make_schedule((bank, savings, "25000"), ends_after=6)
    goal = saving_for(signed_in, savings, "1000000", "2027-10-13", schedules=[sip.pk])

    assert "Projection ₹2,25,000.00" in goal_text(signed_in, goal)


def test_an_open_amount_schedule_counts_what_was_last_paid(
    signed_in: Client, savings: Account, bank: Account
) -> None:
    sip = make_schedule((bank, savings, None))
    paid = Transaction.objects.create(date=date(2026, 9, 5))
    paid.splits.create(from_account=bank, to_account=savings, amount=20000)
    goal = saving_for(signed_in, savings, "1000000", "2027-10-13", schedules=[sip.pk])

    # Savings now holds the 20,000 paid too.
    assert "Projection ₹3,60,000.00" in goal_text(signed_in, goal)


def test_a_paused_schedule_adds_nothing(
    signed_in: Client, savings: Account, bank: Account
) -> None:
    sip = make_schedule((bank, savings, "25000"), active=False)
    goal = saving_for(signed_in, savings, "1000000", "2027-10-13", schedules=[sip.pk])

    assert "Projection ₹1,00,000.00" in goal_text(signed_in, goal)


def test_a_passed_target_date_shows_progress_against_the_target(
    signed_in: Client, savings: Account
) -> None:
    goal = saving_for(signed_in, savings, "150000", "2026-06-30")

    page = goal_text(signed_in, goal)

    assert "Target date passed on 30 Jun 2026" in page
    assert "Short by ₹50,000.00" in page
    assert "Required Monthly Investment" not in page


def test_the_goals_list_shows_each_goals_status(
    signed_in: Client, savings: Account, bank: Account
) -> None:
    saving_for(signed_in, savings, "1000000", "2027-10-13")
    create_goal(signed_in, "Car", "1", "2026-01-31")
    trip = create_goal(signed_in, "Trip", "1000", "2030-01-31")
    assert trip is not None
    allocate(signed_in, trip, source(bank), percent="10")

    page = goals_text(signed_in)

    assert "Behind by ₹9,00,000.00" in page
    assert "Target date passed" in page
    assert "On track" in page
