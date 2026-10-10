from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def pay(
    on: date, source: Account, destination: Account, amount: str, party: Party | None
) -> None:
    transaction = Transaction.objects.create(date=on, party=party)
    transaction.splits.create(
        from_account=source, to_account=destination, amount=Decimal(amount)
    )


def proposed_amounts() -> list[Decimal | None]:
    return [split.amount for split in Draft.objects.get().splits.all()]


def test_an_open_amount_draft_is_prefilled_with_the_last_amount_paid() -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")
    rent = make_account("Rent", "expense")
    bescom = Party.objects.create(name="BESCOM")
    pay(date(2026, 8, 6), bank, power, "1500", bescom)
    pay(date(2026, 9, 7), bank, power, "1800", bescom)
    pay(date(2026, 9, 20), bank, power, "999", None)
    pay(date(2026, 9, 25), bank, rent, "25000", bescom)
    make_schedule((bank, power, None), party=bescom)

    run_daily_job(date(2026, 10, 5))

    assert proposed_amounts() == [Decimal(1800)]
    assert Draft.objects.get().estimated


def test_a_split_with_a_fixed_amount_keeps_it() -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")
    fee = make_account("Fees", "expense")
    pay(date(2026, 9, 7), bank, power, "1800", None)
    pay(date(2026, 9, 7), bank, fee, "40", None)
    make_schedule((bank, power, None), (bank, fee, "50"))

    run_daily_job(date(2026, 10, 5))

    assert proposed_amounts() == [Decimal(1800), Decimal(50)]


def test_with_nothing_paid_before_the_draft_waits_without_an_amount() -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")
    pay(date(2026, 10, 9), bank, power, "1800", None)
    make_schedule((bank, power, None))

    run_daily_job(date(2026, 10, 5))

    assert proposed_amounts() == [None]
    assert not Draft.objects.get().estimated


def test_the_drafts_list_marks_an_estimate(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    power = make_account("Electricity", "expense")
    pay(date(2026, 9, 7), bank, power, "1800", None)
    make_schedule((bank, power, None))
    run_daily_job(date(2026, 10, 5))

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert "Estimate" in body
