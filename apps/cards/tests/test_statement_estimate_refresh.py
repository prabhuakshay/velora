from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.cards.models import CardEMI, Statement
from apps.cards.tests.conftest import make_card_emi, record
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def record_via_form(
    client: Client, source: Account, destination: Account, **fields: str
) -> None:
    client.post(reverse("transaction_create"), form_data(source, destination, **fields))


def edit_spend(client: Client, statement: Statement, **fields: object) -> None:
    """Edit the Statement's only spend, its one Split kept unless changed."""
    spend = statement.card.splits_out.get()
    data = form_data(
        spend.from_account,
        spend.to_account,
        str(spend.amount),
        date=f"{spend.transaction.date:%Y-%m-%d}",
        split_id=spend.pk,
    )
    data.update(fields)
    client.post(reverse("transaction_edit", args=[spend.transaction_id]), data)


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


def test_an_actual_amount_or_a_payment_keeps_what_is_paid(
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
    assert october.estimated_amount == 0
    assert october.amount == Decimal(1000)
    assert october.draft.splits.get().amount == Decimal(1000)


def test_recording_a_transaction_in_a_closed_period_updates_the_estimate(
    signed_in: Client, card: Account, groceries: Account, billed: Statement
) -> None:
    record_via_form(signed_in, card, groceries, amount="400", date="2026-10-10")

    billed.refresh_from_db()
    assert billed.estimated_amount == Decimal(1600)
    assert billed.draft.splits.get().amount == Decimal(1600)


def test_editing_a_transaction_out_of_the_period_updates_the_estimate(
    signed_in: Client, billed: Statement
) -> None:
    edit_spend(signed_in, billed, date="2026-09-10")

    billed.refresh_from_db()
    assert billed.estimated_amount == 0
    assert not Draft.objects.exists()


def test_moving_a_split_off_the_card_updates_the_estimate(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    assert card.pays_from
    edit_spend(signed_in, billed, **{"splits-0-from_account": card.pays_from.pk})

    billed.refresh_from_db()
    assert billed.estimated_amount == 0
    assert not Draft.objects.exists()


def test_deleting_a_transaction_in_a_closed_period_updates_the_estimate(
    signed_in: Client, card: Account, groceries: Account, billed: Statement
) -> None:
    dinner = record(card, groceries, "400", date(2026, 10, 10))
    record_via_form(signed_in, card, groceries, amount="1", date="2026-10-10")

    signed_in.post(reverse("transaction_delete", args=[dinner.pk]))

    billed.refresh_from_db()
    assert billed.estimated_amount == Decimal(1201)
    assert billed.draft.splits.get().amount == Decimal(1201)


def test_deleting_a_card_emi_purchase_updates_the_estimate(
    signed_in: Client, card: Account
) -> None:
    emi = make_card_emi(
        card, principal="3000", months=3, annual_rate="0", bought_on=date(2026, 7, 1)
    )
    run_daily_job(date(2026, 9, 16))
    september = Statement.objects.get()
    assert september.amount == Decimal(1000)

    signed_in.post(reverse("transaction_delete", args=[emi.purchase_id]))

    september.refresh_from_db()
    assert september.estimated_amount == 0
    assert not Draft.objects.exists()


def test_settling_an_older_statement_late_updates_the_next(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    assert card.pays_from
    record(card, groceries, "10000", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    record(card.pays_from, card, "12000", date(2026, 11, 3))
    record(card, groceries, "5000", date(2026, 10, 20))
    run_daily_job(date(2026, 11, 16))
    october, november = Statement.objects.all()
    assert november.amount == Decimal(-7000)
    signed_in.post(
        reverse("statement_edit", args=[october.pk]), {"actual_amount": "12000"}
    )

    run_daily_job(date(2026, 11, 17))

    october.refresh_from_db()
    november.refresh_from_db()
    assert october.transaction
    assert november.estimated_amount == Decimal(5000)
    assert november.draft.splits.get().amount == Decimal(5000)


def test_posting_an_older_payment_draft_late_updates_the_next(
    signed_in: Client,
    card: Account,
    groceries: Account,
    billed: Statement,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # So the payment is dated its due date, inside November's period.
    monkeypatch.setattr(timezone, "localdate", lambda *_a, **_k: date(2026, 11, 20))
    record(card, groceries, "500", date(2026, 10, 20))
    run_daily_job(date(2026, 11, 16))
    november = Statement.objects.get(period_end=date(2026, 11, 15))

    signed_in.post(reverse("draft_post", args=[billed.draft.pk]))

    billed.refresh_from_db()
    november.refresh_from_db()
    assert billed.transaction
    assert november.estimated_amount == Decimal(500)
    assert november.draft.splits.get().amount == Decimal(500)


def test_a_paid_statement_is_never_re_estimated(
    signed_in: Client, card: Account, groceries: Account, billed: Statement
) -> None:
    assert card.pays_from
    record(card.pays_from, card, "1200", date(2026, 11, 3))
    run_daily_job(date(2026, 11, 3))

    record_via_form(signed_in, card, groceries, amount="400", date="2026-10-10")

    billed.refresh_from_db()
    assert billed.transaction
    assert billed.estimated_amount == Decimal(1200)
    assert not Draft.objects.filter(statement=billed).exists()
