from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.cards.models import CardEMI, Statement
from apps.cards.tests.conftest import make_card_emi, record
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_converting_a_purchase_to_a_card_emi_updates_the_waiting_estimate(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    record(card, groceries, "1200", date(2026, 7, 20))
    purchase = record(card, groceries, "3000", date(2026, 8, 1))
    run_daily_job(date(2026, 8, 16))
    august = Statement.objects.get()
    assert august.amount == Decimal(4200)

    signed_in.post(
        reverse("card_emi_create", args=[purchase.pk]),
        {
            "principal": "3000",
            "months": "3",
            "annual_rate": "0",
            "processing_fee": "0",
            "first_statement": "2026-09-15",
            "interest_account": groceries.pk,
        },
    )

    august.refresh_from_db()
    assert CardEMI.objects.exists()
    assert august.estimated_amount == Decimal(1200)
    assert august.draft.splits.get().amount == Decimal(1200)


def test_foreclosing_a_card_emi_updates_the_waiting_estimate(
    signed_in: Client, card: Account
) -> None:
    emi = make_card_emi(
        card, principal="3000", months=3, annual_rate="0", bought_on=date(2026, 7, 1)
    )
    run_daily_job(date(2026, 9, 16))
    september = Statement.objects.get(period_end=date(2026, 9, 15))
    assert september.amount == Decimal(1000)

    signed_in.post(
        reverse("card_emi_foreclose", args=[emi.pk]),
        {"foreclosed_on": "2026-09-01", "foreclosure_fee": "100"},
    )

    september.refresh_from_db()
    assert september.estimated_amount == Decimal(3100)
    assert september.draft.splits.get().amount == Decimal(3100)


def test_a_statement_with_an_actual_amount_or_a_payment_is_left_alone(
    signed_in: Client, card: Account
) -> None:
    assert card.pays_from
    emi = make_card_emi(
        card, principal="3000", months=3, annual_rate="0", bought_on=date(2026, 7, 1)
    )
    run_daily_job(date(2026, 9, 16))
    record(card.pays_from, card, "1000", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    september, october = Statement.objects.all()
    assert september.transaction
    signed_in.post(
        reverse("statement_edit", args=[october.pk]), {"actual_amount": "1000"}
    )

    signed_in.post(
        reverse("card_emi_foreclose", args=[emi.pk]),
        {"foreclosed_on": "2026-09-01", "foreclosure_fee": "100"},
    )

    september.refresh_from_db()
    october.refresh_from_db()
    assert september.estimated_amount == Decimal(1000)
    assert october.estimated_amount == Decimal(1000)
    assert october.draft.splits.get().amount == Decimal(1000)
