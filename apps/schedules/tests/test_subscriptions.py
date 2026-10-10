from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.tests.conftest import make_account
from apps.schedules.models import Schedule, ScheduleSplit
from apps.schedules.tests.conftest import make_schedule, schedule_form_data

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User


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


def page_text(signed_in: Client, query: str = "") -> str:
    response = signed_in.get(reverse("subscription_list") + query)
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


def test_open_paused_and_ended_subscriptions_stay_out_of_the_totals(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    services = make_account("Services", "expense")
    make_schedule((bank, services, "100"), description="Music", is_subscription=True)
    make_schedule((bank, services, None), description="Cloud", is_subscription=True)
    make_schedule(
        (bank, services, "500"),
        description="Gym",
        is_subscription=True,
        active=False,
    )
    make_schedule(
        (bank, services, "300"),
        description="News",
        is_subscription=True,
        ends_on=timezone.localdate() - timedelta(days=1),
    )

    text = page_text(signed_in)

    assert "Cloud Every month Open amount" in text
    assert "Gym Every month · Paused ₹500.00" in text
    assert "News Every month · Ended" in text
    assert "Total ₹100.00 a month · ₹1,200.00 a year" in text


def test_costs_follow_the_number_format(signed_in: Client, user: User) -> None:
    bank = make_account("Bank", "asset")
    services = make_account("Services", "expense")
    make_schedule(
        (bank, services, "125000"),
        description="Software",
        unit="year",
        is_subscription=True,
    )
    user.number_format = "international"
    user.save()

    text = page_text(signed_in)

    assert "₹10,416.67 a month · ₹125,000.00 a year" in text


def test_privacy_mode_hides_every_cost(signed_in: Client, user: User) -> None:
    bank = make_account("Bank", "asset")
    services = make_account("Services", "expense")
    make_schedule(
        (bank, services, "649"), description="Streaming", is_subscription=True
    )
    user.privacy_mode = True
    user.save()

    text = page_text(signed_in)

    assert "Streaming Every month ₹•••• ₹•••• a month · ₹•••• a year" in text
    assert "Total ₹•••• a month · ₹•••• a year" in text
    assert "649" not in text
    assert "7,788" not in text


def priced(split: ScheduleSplit, amount: str, on: date) -> None:
    split.amount = Decimal(amount)
    # Backdates the history record, as if the price changed on that day.
    split._history_date = datetime.combine(on, time(12), tzinfo=UTC)  # type: ignore[attr-defined]  # noqa: SLF001
    split.save()


def test_a_subscription_shows_how_its_amount_changed(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    services = make_account("Services", "expense")
    streaming = make_schedule(description="Streaming", is_subscription=True)
    split = ScheduleSplit(schedule=streaming, from_account=bank, to_account=services)
    priced(split, "499", date(2025, 1, 10))
    priced(split, "499", date(2025, 3, 10))
    priced(split, "599", date(2025, 6, 1))
    priced(split, "649", date(2026, 2, 1))
    make_schedule((bank, services, "99"), description="Music", is_subscription=True)

    text = page_text(signed_in)

    assert (
        "Streaming Every month ₹649.00 ₹649.00 a month · ₹7,788.00 a year"
        " Price history: ₹499.00 from 10 Jan 2025 · ₹599.00 from 1 Jun 2025"
        " · ₹649.00 from 1 Feb 2026"
    ) in text
    assert text.count("Price history") == 1


def test_the_list_is_paginated_with_totals_over_every_subscription(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    services = make_account("Services", "expense")
    for number in range(1, 27):
        make_schedule(
            (bank, services, "10"),
            description=f"Service {number:02}",
            is_subscription=True,
        )

    first = page_text(signed_in)
    second = page_text(signed_in, "?page=2")

    assert "Service 01" in first
    assert "Service 26" not in first
    assert "Service 26" in second
    assert "Service 01" not in second
    for text in (first, second):
        assert "Total ₹260.00 a month · ₹3,120.00 a year" in text
