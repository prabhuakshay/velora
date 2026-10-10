from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.cards.statements import estimate_statement_amount
from apps.cards.tests.conftest import make_card_emi
from apps.quick_add.models import Draft
from apps.quick_add.posting import post_draft
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def emi_drafts() -> list[tuple[date, list[tuple[str, str, Decimal | None]]]]:
    return [
        (
            draft.date,
            [
                (str(split.from_account), str(split.to_account), split.amount)
                for split in draft.splits.all()
            ],
        )
        for draft in Draft.objects.filter(source=Draft.Source.CARD_EMI).order_by("date")
    ]


def test_each_statement_day_proposes_the_interest_and_gst(card: Account) -> None:
    make_card_emi(card)

    run_daily_job(date(2026, 10, 15))

    # 1250.00 + 225.00 GST, then 1152.80 + 207.50 GST.
    assert emi_drafts() == [
        (date(2026, 9, 15), [("HDFC card", "EMI interest", Decimal("1475.00"))]),
        (date(2026, 10, 15), [("HDFC card", "EMI interest", Decimal("1360.30"))]),
    ]


def test_the_processing_fee_arrives_with_the_first_installment(
    card: Account,
) -> None:
    make_card_emi(card, processing_fee="199")

    run_daily_job(date(2026, 9, 15))

    assert emi_drafts() == [
        (
            date(2026, 9, 15),
            [
                ("HDFC card", "EMI interest", Decimal("1475.00")),
                ("HDFC card", "EMI interest", Decimal(199)),
            ],
        ),
    ]


def test_a_second_run_proposes_nothing_new(card: Account) -> None:
    make_card_emi(card)
    run_daily_job(date(2026, 9, 15))
    Draft.objects.filter(source=Draft.Source.CARD_EMI).get().reject()

    run_daily_job(date(2026, 9, 15))
    run_daily_job(date(2026, 9, 20))

    assert Draft.objects.filter(source=Draft.Source.CARD_EMI).count() == 1


def test_a_no_cost_emi_proposes_nothing(card: Account) -> None:
    make_card_emi(card, annual_rate="0")

    run_daily_job(date(2026, 10, 15))

    assert emi_drafts() == []


def test_a_foreclosed_emi_stops_proposing(card: Account) -> None:
    emi = make_card_emi(card)
    emi.foreclosed_on = date(2026, 10, 1)
    emi.save()

    run_daily_job(date(2026, 11, 15))

    assert [day for day, _ in emi_drafts()] == [date(2026, 9, 15)]


def test_a_posted_interest_draft_is_not_counted_twice(card: Account) -> None:
    make_card_emi(card)
    run_daily_job(date(2026, 9, 15))

    post_draft(Draft.objects.get(source=Draft.Source.CARD_EMI))

    september = (date(2026, 8, 16), date(2026, 9, 15))
    assert estimate_statement_amount(card, *september) == Decimal("9250.83")
