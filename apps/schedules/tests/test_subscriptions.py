from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils.html import strip_tags

from apps.accounts.tests.conftest import make_account
from apps.schedules.models import Schedule
from apps.schedules.tests.conftest import make_schedule, schedule_form_data

if TYPE_CHECKING:
    from django.test import Client


pytestmark = pytest.mark.django_db


def test_a_schedule_is_marked_as_a_subscription_with_its_details(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    streaming = make_account("Streaming", "expense")

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data(
            (bank, streaming, "649"),
            is_subscription="on",
            trial_ends_on="2026-11-01",
            plan="Premium",
            how_to_cancel="Account > Membership > Cancel",
        ),
    )

    schedule = Schedule.objects.get()
    assert (
        schedule.is_subscription,
        schedule.trial_ends_on,
        schedule.plan,
        schedule.how_to_cancel,
    ) == (True, date(2026, 11, 1), "Premium", "Account > Membership > Cancel")


def page_text(signed_in: Client) -> str:
    response = signed_in.get(reverse("subscription_list"))
    return " ".join(strip_tags(response.content.decode()).split())


def test_subscriptions_show_their_monthly_and_yearly_cost_and_totals(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    services = make_account("Services", "expense")
    make_schedule(
        (bank, services, "649"), description="Streaming", is_subscription=True
    )
    make_schedule(
        (bank, services, "1200"),
        description="Domain",
        unit="year",
        is_subscription=True,
    )
    make_schedule((bank, services, "25000"), description="Rent")

    text = page_text(signed_in)

    assert "Streaming Every month ₹649.00 ₹649.00 a month · ₹7,788.00 a year" in text
    assert "Domain Every year ₹1,200.00 ₹100.00 a month · ₹1,200.00 a year" in text
    assert "Rent" not in text
    assert "Total ₹749.00 a month · ₹8,988.00 a year" in text
