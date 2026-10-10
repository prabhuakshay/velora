from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Occurrence, Schedule
from apps.schedules.tests.conftest import (
    make_schedule,
    paid,
    schedule_form_data,
)
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client


pytestmark = pytest.mark.django_db


def test_a_schedule_is_created_from_its_template_and_rule(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    landlord = Party.objects.create(name="Landlord")

    response = signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "25000"), party=landlord.pk, every=2),
    )

    schedule = Schedule.objects.get()
    assert response["Location"] == reverse("schedule_detail", args=[schedule.pk])
    assert (
        schedule.party,
        schedule.description,
        schedule.start_date,
        schedule.every,
        schedule.unit,
    ) == (landlord, "Flat rent", date(2026, 10, 5), 2, "month")
    assert [
        (split.from_account, split.to_account, split.amount)
        for split in schedule.splits.all()
    ] == [(bank, rent, Decimal(25000))]


def test_a_new_schedule_lays_out_its_upcoming_occurrences(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    start = timezone.localdate() + timedelta(days=1)

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "25000"), start_date=start, unit="week"),
    )

    occurrences = Schedule.objects.get().occurrences.all()
    assert [(o.due_date, o.status) for o in occurrences][:2] == [
        (start, Occurrence.Status.UPCOMING),
        (start + timedelta(weeks=1), Occurrence.Status.UPCOMING),
    ]


def test_a_new_schedule_already_due_proposes_its_draft_at_once(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Food", "expense")
    yesterday = timezone.localdate() - timedelta(days=1)

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, food, "100"), start_date=yesterday, unit="day"),
    )

    assert [draft.date for draft in Draft.objects.order_by("date")] == [
        yesterday,
        yesterday + timedelta(days=1),
    ]


def test_a_new_schedule_already_paid_proposes_no_draft(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    phone = make_account("Phone", "expense")
    today = timezone.localdate()
    paid((bank, phone), Party.objects.create(name="Airtel"), ("990", today))

    signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, phone, "1000"), start_date=today),
    )

    assert not Draft.objects.exists()
    assert Occurrence.objects.get(due_date=today).status == Occurrence.Status.PAID


def test_splits_follow_the_transaction_split_rules(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    card = make_account("Card", "liability")
    rent = make_account("Rent", "expense")
    salary = make_account("Salary", "income")
    food = make_account("Food", "expense")

    crossed = signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "100"), (card, food, "50")),
    )
    into_income = signed_in.post(
        reverse("schedule_create"), schedule_form_data((bank, salary, "100"))
    )
    no_splits = signed_in.post(reverse("schedule_create"), schedule_form_data())
    to_itself = signed_in.post(
        reverse("schedule_create"), schedule_form_data((bank, bank, "100"))
    )

    assert "Splits must share a From or a To Account." in crossed.content.decode()
    assert "An Income Account can only be a source." in into_income.content.decode()
    assert "Add at least one Split." in no_splits.content.decode()
    assert "A Split cannot go from an Account to itself." in to_itself.content.decode()
    assert not Schedule.objects.exists()


def test_a_split_amount_may_be_left_open(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")

    signed_in.post(reverse("schedule_create"), schedule_form_data((bank, power, "")))

    assert [split.amount for split in Schedule.objects.get().splits.all()] == [None]


def test_the_last_due_date_cannot_be_before_the_first(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")

    response = signed_in.post(
        reverse("schedule_create"),
        schedule_form_data((bank, rent, "100"), ends_on="2026-10-01"),
    )

    assert "The last due date cannot be before the first." in response.content.decode()
    assert not Schedule.objects.exists()


def test_the_list_shows_each_schedules_next_due_date_and_amount(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    power = make_account("Electricity", "expense")
    soon = timezone.localdate() + timedelta(days=2)
    for description, split in [
        ("Flat rent", (bank, rent, "25000")),
        ("Power bill", (bank, power, "")),
    ]:
        signed_in.post(
            reverse("schedule_create"),
            schedule_form_data(split, description=description, start_date=soon),
        )

    body = signed_in.get(reverse("schedule_list")).content.decode()

    assert body.index("Flat rent") < body.index("₹25,000.00")
    assert body.index("Power bill") < body.index("Open amount")
    assert body.count(f"Next due {soon:%-d %b %Y}") == 2
    for schedule in Schedule.objects.all():
        assert reverse("schedule_detail", args=[schedule.pk]) in body
    assert reverse("schedule_create") in body


def test_the_detail_page_shows_the_occurrence_history(signed_in: Client) -> None:
    schedule = make_schedule(description="Flat rent", start_date=date(2026, 8, 5))
    schedule.occurrences.create(
        due_date=date(2026, 8, 5), status=Occurrence.Status.PAID
    )
    schedule.occurrences.create(
        due_date=date(2026, 9, 5), status=Occurrence.Status.SKIPPED
    )
    schedule.occurrences.create(due_date=date(2026, 10, 5))

    body = signed_in.get(
        reverse("schedule_detail", args=[schedule.pk])
    ).content.decode()

    assert "Every 1 month from 5 Aug 2026" in body
    assert body.index("5 Aug 2026 · Paid") < body.index("5 Sep 2026 · Skipped")
    assert body.index("5 Sep 2026 · Skipped") < body.index("5 Oct 2026 · Upcoming")


def test_the_occurrence_history_links_to_each_draft_and_transaction(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    schedule = make_schedule((bank, rent, "25000"), start_date=date(2026, 9, 5))
    payment = Transaction.objects.create(date=date(2026, 9, 5))
    payment.splits.create(from_account=bank, to_account=rent, amount=Decimal(25000))
    run_daily_job(date(2026, 10, 5))

    body = signed_in.get(
        reverse("schedule_detail", args=[schedule.pk])
    ).content.decode()

    draft = Draft.objects.get()
    assert f'href="{reverse("transaction_edit", args=[payment.pk])}"' in body
    assert f'href="{reverse("draft_edit", args=[draft.pk])}"' in body


def test_editing_changes_only_upcoming_occurrences(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda *_a, **_k: date(2026, 10, 9))
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    schedule = make_schedule((bank, rent, "25000"), start_date=date(2026, 8, 5))
    for due, status in [
        (date(2026, 8, 5), Occurrence.Status.PAID),
        (date(2026, 9, 5), Occurrence.Status.SKIPPED),
        (date(2026, 10, 5), Occurrence.Status.DRAFTED),
        (date(2026, 11, 5), Occurrence.Status.UPCOMING),
    ]:
        schedule.occurrences.create(due_date=due, status=status)
    split = schedule.splits.get()

    response = signed_in.post(
        reverse("schedule_edit", args=[schedule.pk]),
        schedule_form_data(
            (bank, rent, "27000"),
            start_date="2026-08-10",
            **{"splits-INITIAL_FORMS": 1, "splits-0-id": split.pk},
        ),
    )

    assert response["Location"] == reverse("schedule_detail", args=[schedule.pk])
    kept = [
        (o.due_date, o.status)
        for o in schedule.occurrences.exclude(status=Occurrence.Status.UPCOMING)
    ]
    assert kept == [
        (date(2026, 8, 5), Occurrence.Status.PAID),
        (date(2026, 9, 5), Occurrence.Status.SKIPPED),
        (date(2026, 10, 5), Occurrence.Status.DRAFTED),
    ]
    upcoming = schedule.occurrences.filter(status=Occurrence.Status.UPCOMING)
    assert upcoming[0].due_date == date(2026, 10, 10)
    assert schedule.splits.get().amount == Decimal(27000)
    assert schedule.history.count() == 2


def test_schedules_need_sign_in(client: Client) -> None:
    schedule = make_schedule()

    for url in (
        reverse("schedule_list"),
        reverse("schedule_create"),
        reverse("schedule_detail", args=[schedule.pk]),
        reverse("schedule_edit", args=[schedule.pk]),
    ):
        assert client.get(url)["Location"].startswith(reverse("login"))


def test_every_page_links_to_schedules(signed_in: Client) -> None:
    body = signed_in.get(reverse("transaction_list")).content.decode()

    assert f'href="{reverse("schedule_list")}"' in body


def test_add_split_gives_a_numbered_blank_row(signed_in: Client) -> None:
    body = signed_in.get(
        reverse("schedule_split_row"), {"splits-TOTAL_FORMS": "1"}
    ).content.decode()

    assert 'name="splits-1-amount"' in body
    assert 'name="splits-TOTAL_FORMS" value="2"' in body
