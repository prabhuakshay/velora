from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.schedules.daily_job import run_daily_job
from apps.schedules.tests.conftest import make_schedule

if TYPE_CHECKING:
    from django.test import Client

    from apps.schedules.models import Schedule
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def rent_due_in_two_days() -> Schedule:
    today = timezone.localdate()
    schedule = make_schedule(
        (make_account("Bank", "asset"), make_account("Rent", "expense"), "25000"),
        description="Flat rent",
        start_date=today + timedelta(days=2),
    )
    run_daily_job(today)
    return schedule


def test_the_home_page_shows_the_upcoming_items(signed_in: Client) -> None:
    schedule = rent_due_in_two_days()

    page = signed_in.get(reverse("index")).content.decode()

    assert "Upcoming" in page
    assert "Coming up" in page
    assert "Flat rent" in page
    assert "₹25,000.00" in page
    assert f'href="{reverse("schedule_detail", args=[schedule.pk])}"' in page


def test_the_upcoming_panel_honours_privacy_mode(signed_in: Client, user: User) -> None:
    rent_due_in_two_days()
    user.set_privacy_mode(on=True)

    page = signed_in.get(reverse("index")).content.decode()

    assert "Flat rent" in page
    assert "25,000" not in page


def test_the_upcoming_panel_says_when_nothing_needs_the_user(
    signed_in: Client,
) -> None:
    page = signed_in.get(reverse("index")).content.decode()

    assert "Nothing needs you today." in page


def test_the_upcoming_panel_warns_of_a_low_balance(signed_in: Client) -> None:
    rent_due_in_two_days()

    page = signed_in.get(reverse("index")).content.decode()

    assert "Low balance" in page
    assert f'href="{reverse("forecast")}"' in page
    assert "-₹25,000.00" in page
