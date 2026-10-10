from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.schedules.models import Schedule
from apps.schedules.tests.conftest import make_schedule, schedule_form_data

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_a_cron_rule_replaces_the_interval(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "100"), cron="0 0 * * 5#2"),
    )

    schedule = Schedule.objects.get()
    assert (schedule.cron, schedule.every, schedule.unit) == ("0 0 * * 5#2", None, "")


@pytest.mark.parametrize("cron", ["0 0 * * fri#9", "0 0 31 2 *"])
def test_an_invalid_cron_expression_is_refused(signed_in: Client, cron: str) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    response = signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "100"), cron=cron),
    )

    assert "Not a valid cron expression." in response.content.decode()
    assert not Schedule.objects.exists()


def test_a_rule_needs_an_interval_or_a_cron_expression(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    response = signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "100"), every="", unit=""),
    )

    assert "Repeat every so often or on a cron expression." in (
        response.content.decode()
    )
    assert not Schedule.objects.exists()


def test_a_schedule_can_stop_after_a_number_of_occurrences(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "100"), ends_after=6),
    )

    assert Schedule.objects.get().ends_after == 6


def test_auto_post_is_saved_for_fixed_amounts(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "25000"), auto_post="on"),
    )

    assert Schedule.objects.get().auto_post


def test_auto_post_is_refused_when_an_amount_is_open(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    fee = make_account("Fees", "expense")

    response = signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "25000"), (bank, fee, ""), auto_post="on"),
    )

    assert "Auto-post needs an amount on every Split." in response.content.decode()
    assert not Schedule.objects.exists()


def test_the_detail_page_describes_cron_end_and_auto_post_rules(
    signed_in: Client,
) -> None:
    schedule = make_schedule(
        start_date=date(2026, 10, 1),
        every=None,
        unit="",
        cron="0 0 * * 5#2",
        ends_after=6,
        auto_post=True,
    )

    body = signed_in.get(
        reverse("schedule_detail", args=[schedule.pk])
    ).content.decode()

    assert "On cron 0 0 * * 5#2 from 1 Oct 2026, 6 times" in body
    assert "Auto-post" in body
