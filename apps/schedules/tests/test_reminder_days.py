from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.schedules.models import Schedule
from apps.schedules.tests.conftest import schedule_form_data

if TYPE_CHECKING:
    from django.test import Client


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("unit", "expected"), [("day", 0), ("week", 1), ("month", 3), ("year", 14)]
)
def test_blank_reminder_days_default_by_interval(
    signed_in: Client, unit: str, expected: int
) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "25000"), unit=unit, reminder_days=""),
    )

    assert Schedule.objects.get().reminder_days == expected


def test_reminder_days_can_be_set_per_schedule(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    insurance = make_account("Insurance", "expense")

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, insurance, "18000"), unit="year", reminder_days=30),
    )

    assert Schedule.objects.get().reminder_days == 30


def test_the_new_schedule_form_leaves_reminder_days_blank(signed_in: Client) -> None:
    response = signed_in.get(reverse("schedule_create"))

    assert response.context["form"]["reminder_days"].value() is None
