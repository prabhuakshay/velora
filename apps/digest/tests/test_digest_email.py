from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.core import mail
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.cards.tests.conftest import make_card, record
from apps.quick_add.models import Draft
from apps.quick_add.tests.conftest import make_manual_draft
from apps.schedules.daily_job import DailyJobError, run_daily_job
from apps.schedules.tests.conftest import make_schedule

if TYPE_CHECKING:
    from pytest_django import Settings

    from apps.users.models import User

pytestmark = pytest.mark.django_db

SITE = "https://velora.example"
MAIL_DOWN = "Mail server down"


@pytest.fixture(autouse=True)
def _site(settings: Settings) -> None:
    settings.SITE_URL = SITE


def test_the_digest_reminds_of_occurrences_within_their_lead_days(user: User) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    schedule = make_schedule((bank, rent, "25000"), description="Flat rent")

    run_daily_job(date(2026, 10, 2))

    [email] = mail.outbox
    assert email.to == [user.email]
    assert "Flat rent" in email.body
    assert "5 Oct 2026" in email.body
    assert "₹25,000.00" in email.body
    assert SITE + reverse("schedule_detail", args=[schedule.pk]) in email.body


@pytest.mark.usefixtures("user")
def test_the_digest_shows_an_occurrence_drafted_today() -> None:
    bank = make_account("Bank", "asset")
    bank.opening_balance = Decimal(100000)
    bank.save()
    make_schedule(
        (bank, make_account("Milk", "expense"), "60"),
        description="Milk",
        unit="day",
        reminder_days=0,
    )

    run_daily_job(date(2026, 10, 5))

    [email] = mail.outbox
    assert "Coming up" in email.body
    assert "5 Oct 2026: Milk, ₹60.00" in email.body
    draft = Draft.objects.get()
    assert SITE + reverse("draft_edit", args=[draft.pk]) in email.body


def rent() -> None:
    """Rent from a Bank that can afford it, so no low-balance warning shows."""
    bank = make_account("Bank", "asset")
    bank.opening_balance = Decimal(100000)
    bank.save()
    make_schedule(
        (bank, make_account("Rent", "expense"), "25000"), description="Flat rent"
    )


@pytest.mark.usefixtures("user")
def test_no_digest_is_sent_on_a_day_with_nothing_to_report() -> None:
    rent()

    run_daily_job(date(2026, 9, 20))

    assert mail.outbox == []


@pytest.mark.usefixtures("user")
def test_running_twice_on_the_same_day_sends_one_digest() -> None:
    rent()

    run_daily_job(date(2026, 10, 2))
    run_daily_job(date(2026, 10, 2))
    run_daily_job(date(2026, 10, 3))

    assert len(mail.outbox) == 2


def test_a_failed_send_is_retried_only_for_users_not_yet_sent(
    user: User, superuser: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    rent()

    def fail_for_admin(*args: Any, **kwargs: Any) -> int:
        if args[3] == [superuser.email]:
            raise OSError(MAIL_DOWN)
        return send_mail(*args, **kwargs)

    monkeypatch.setattr("apps.digest.email.send_mail", fail_for_admin)
    with pytest.raises(DailyJobError):
        run_daily_job(date(2026, 10, 2))
    monkeypatch.setattr("apps.digest.email.send_mail", send_mail)

    run_daily_job(date(2026, 10, 2))

    assert sorted(email.to[0] for email in mail.outbox) == sorted(
        [user.email, superuser.email]
    )


@pytest.mark.usefixtures("user")
def test_the_digest_shows_an_overdue_occurrence_within_its_grace_days() -> None:
    rent()

    run_daily_job(date(2026, 10, 7))

    [email] = mail.outbox
    assert "Coming up" in email.body
    assert "5 Oct 2026: Flat rent" in email.body
    draft = Draft.objects.get()
    assert SITE + reverse("draft_edit", args=[draft.pk]) in email.body


@pytest.mark.usefixtures("user")
def test_the_digest_lists_missed_occurrences_with_their_draft() -> None:
    rent()

    run_daily_job(date(2026, 10, 9))

    [email] = mail.outbox
    assert "Missed" in email.body
    assert "5 Oct 2026: Flat rent" in email.body
    draft = Draft.objects.get()
    assert SITE + reverse("draft_edit", args=[draft.pk]) in email.body


@pytest.mark.usefixtures("user")
def test_the_digest_shows_a_card_due_day_with_its_statement_amount() -> None:
    bank = make_account("Bank", "asset")
    bank.opening_balance = Decimal(5000)
    bank.save()
    card = make_card(pays_from=bank)
    record(card, make_account("Groceries", "expense"), "1200", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 15))
    assert mail.outbox == []

    run_daily_job(date(2026, 11, 2))

    [email] = mail.outbox
    assert "Card Due Days" in email.body
    assert "5 Nov 2026: HDFC card, ₹1,200.00" in email.body
    payment = Draft.objects.get()
    assert SITE + reverse("draft_edit", args=[payment.pk]) in email.body


def made_on(made: date, draft: Draft) -> None:
    Draft.objects.filter(pk=draft.pk).update(
        created_at=datetime.combine(
            made, time(), tzinfo=timezone.get_current_timezone()
        )
    )


def dentist_draft_made_on(made: date) -> Draft:
    bank = make_account("Bank", "asset")
    dentist = make_account("Dentist", "expense")
    draft = make_manual_draft((bank, dentist, None), description="Dentist")
    made_on(made, draft)
    return draft


@pytest.mark.usefixtures("user")
def test_the_digest_lists_drafts_waiting_seven_days() -> None:
    draft = dentist_draft_made_on(date(2026, 10, 1))

    run_daily_job(date(2026, 10, 7))
    assert mail.outbox == []

    run_daily_job(date(2026, 10, 8))

    [email] = mail.outbox
    assert "Drafts waiting 7 days" in email.body
    assert "8 Oct 2026: Dentist, ₹?" in email.body
    assert SITE + reverse("draft_edit", args=[draft.pk]) in email.body


@pytest.mark.usefixtures("user")
def test_a_missed_occurrences_old_draft_is_listed_once() -> None:
    rent()
    run_daily_job(date(2026, 10, 9))
    made_on(date(2026, 10, 1), Draft.objects.get())

    run_daily_job(date(2026, 10, 10))

    assert mail.outbox[-1].body.count("Flat rent") == 1


@pytest.mark.usefixtures("user")
def test_an_old_draft_within_long_grace_days_is_listed_once() -> None:
    bank = make_account("Bank", "asset")
    bank.opening_balance = Decimal(100000)
    bank.save()
    make_schedule(
        (bank, make_account("Rent", "expense"), "25000"),
        description="Flat rent",
        grace_days=10,
    )
    run_daily_job(date(2026, 10, 5))
    made_on(date(2026, 10, 5), Draft.objects.get())

    run_daily_job(date(2026, 10, 13))

    assert mail.outbox[-1].body.count("Flat rent") == 1


@pytest.mark.usefixtures("user")
def test_each_occurrence_within_its_lead_days_is_reminded() -> None:
    make_schedule(
        (make_account("Bank", "asset"), make_account("Gym", "expense"), "500"),
        description="Gym",
        unit="week",
        reminder_days=14,
    )

    run_daily_job(date(2026, 10, 6))

    body = mail.outbox[0].body
    assert "5 Oct 2026: Gym" in body
    assert "12 Oct 2026: Gym" in body
    assert "19 Oct 2026: Gym" in body
    assert "26 Oct 2026: Gym" not in body


def test_the_digest_masks_amounts_in_privacy_mode(user: User) -> None:
    user.set_privacy_mode(on=True)
    rent()

    run_daily_job(date(2026, 10, 2))

    body = mail.outbox[0].body
    assert "Flat rent, ₹••••" in body
    assert "25,000" not in body
    assert "<span" not in body


@pytest.mark.usefixtures("user")
def test_the_digest_warns_of_a_low_balance_with_its_first_day() -> None:
    bank = make_account("Salary bank", "asset")
    bank.opening_balance = Decimal(10000)
    bank.save()
    make_schedule((bank, make_account("Rent", "expense"), "25000"))

    run_daily_job(date(2026, 9, 20))

    [email] = mail.outbox
    assert "Low balance" in email.body
    assert "5 Oct 2026: Salary bank, -₹15,000.00" in email.body
    assert SITE + reverse("forecast") in email.body
