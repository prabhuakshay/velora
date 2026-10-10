from datetime import date

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence
from apps.schedules.tests.conftest import make_schedule, paid

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda *_a, **_k: date(2026, 10, 5))


def test_proposes_drafts_for_schedules_due_by_today() -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    make_schedule((bank, rent, "25000"), start_date=date(2026, 10, 5))
    make_schedule((bank, rent, "500"), start_date=date(2026, 10, 6))

    call_command("propose_drafts")

    assert [draft.date for draft in Draft.objects.all()] == [date(2026, 10, 5)]


def test_a_recorded_transaction_needs_no_draft() -> None:
    bank = make_account("Bank", "asset")
    phone = make_account("Phone", "expense")
    make_schedule((bank, phone, "1000"))
    paid((bank, phone), Party.objects.create(name="Airtel"), ("990", date(2026, 10, 5)))

    call_command("propose_drafts")

    assert not Draft.objects.exists()
    assert Occurrence.objects.get(due_date=date(2026, 10, 5)).status == (
        Occurrence.Status.PAID
    )
