from datetime import date

import pytest

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence, Schedule
from apps.schedules.occurrences import materialise, propose_draft, regenerate
from apps.schedules.tests.conftest import make_schedule

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 5)


def loaded_occurrence() -> Occurrence:
    """A due Occurrence as the daily job holds it, before anything else runs."""
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    materialise(make_schedule((bank, rent, "25000")), TODAY)
    return Occurrence.objects.select_related("schedule").get(due_date=TODAY)


def test_an_occurrence_deleted_by_an_edit_gets_no_draft() -> None:
    occurrence = loaded_occurrence()
    occurrence.schedule.description = "New rent"
    occurrence.schedule.save()
    regenerate(occurrence.schedule, TODAY)

    propose_draft(occurrence)

    assert [draft.description for draft in Draft.objects.all()] == ["New rent"]


def test_an_already_drafted_occurrence_gets_no_second_draft() -> None:
    occurrence = loaded_occurrence()
    propose_draft(Occurrence.objects.get(pk=occurrence.pk))

    propose_draft(occurrence)

    assert Draft.objects.count() == 1


def test_an_occurrence_of_a_schedule_paused_since_loading_gets_no_draft() -> None:
    occurrence = loaded_occurrence()
    Schedule.objects.update(active=False)

    propose_draft(occurrence)

    assert not Draft.objects.exists()
