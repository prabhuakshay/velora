from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Occurrence
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def proposed_draft() -> Draft:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    make_schedule((bank, rent, "25000"), start_date=date(2026, 10, 5))
    run_daily_job(date(2026, 10, 5))
    return Draft.objects.get()


def statuses() -> list[tuple[date, str]]:
    return [(o.due_date, o.status) for o in Occurrence.objects.all()][:1]


def test_proposing_a_draft_marks_its_occurrence_drafted() -> None:
    proposed_draft()

    assert statuses() == [(date(2026, 10, 5), Occurrence.Status.DRAFTED)]


def test_posting_a_schedules_draft_marks_its_occurrence_paid(
    signed_in: Client,
) -> None:
    draft = proposed_draft()

    signed_in.post(reverse("draft_post", args=[draft.pk]))

    assert Transaction.objects.count() == 1
    assert statuses() == [(date(2026, 10, 5), Occurrence.Status.PAID)]


def test_rejecting_a_schedules_draft_marks_its_occurrence_skipped(
    signed_in: Client,
) -> None:
    draft = proposed_draft()

    signed_in.post(reverse("draft_reject", args=[draft.pk]))

    assert statuses() == [(date(2026, 10, 5), Occurrence.Status.SKIPPED)]


def test_a_refused_post_leaves_the_occurrence_drafted(signed_in: Client) -> None:
    draft = proposed_draft()
    draft.splits.update(to_account=None)

    signed_in.post(reverse("draft_post", args=[draft.pk]))

    assert statuses() == [(date(2026, 10, 5), Occurrence.Status.DRAFTED)]
