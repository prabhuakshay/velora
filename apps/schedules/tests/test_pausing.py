from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Schedule
from apps.schedules.tests.conftest import make_schedule, schedule_form_data

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def daily_schedule(client: Client, start: date) -> Schedule:
    bank = make_account("Bank", "asset")
    food = make_account("Food", "expense")
    client.post(
        reverse("schedule_create"),
        schedule_form_data((bank, food, "100"), start_date=start, unit="day"),
    )
    return Schedule.objects.get()


def draft_dates() -> list[date]:
    return [draft.date for draft in Draft.objects.order_by("date")]


def test_a_paused_schedule_proposes_nothing(signed_in: Client) -> None:
    today = timezone.localdate()
    schedule = daily_schedule(signed_in, today)

    signed_in.post(reverse("schedule_pause", args=[schedule.pk]))
    run_daily_job(today + timedelta(days=2))

    assert not Draft.objects.exists()
    body = signed_in.get(reverse("schedule_detail", args=[schedule.pk])).content
    assert "Paused" in body.decode()


def test_resuming_does_not_catch_up_dates_while_paused(signed_in: Client) -> None:
    today = timezone.localdate()
    schedule = daily_schedule(signed_in, today - timedelta(days=3))
    signed_in.post(reverse("schedule_pause", args=[schedule.pk]))

    signed_in.post(reverse("schedule_resume", args=[schedule.pk]))
    run_daily_job(today + timedelta(days=1))

    assert draft_dates() == [today, today + timedelta(days=1)]


def test_an_ended_schedule_proposes_nothing_from_today(signed_in: Client) -> None:
    today = timezone.localdate()
    schedule = daily_schedule(signed_in, today)

    signed_in.post(reverse("schedule_end", args=[schedule.pk]))
    run_daily_job(today + timedelta(days=2))

    assert not Draft.objects.exists()
    body = signed_in.get(reverse("schedule_detail", args=[schedule.pk])).content
    assert "Ended" in body.decode()


def test_pausing_and_ending_need_a_post(signed_in: Client) -> None:
    schedule = make_schedule()

    for name in ("schedule_pause", "schedule_resume", "schedule_end"):
        response = signed_in.get(reverse(name, args=[schedule.pk]))
        assert response.status_code == 405
