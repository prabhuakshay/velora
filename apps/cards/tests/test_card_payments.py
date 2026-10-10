from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.cards.models import Statement
from apps.cards.tests.conftest import record
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


@pytest.fixture
def billed(card: Account, groceries: Account) -> Statement:
    """The card's Statement to 15 Oct 2026, of 1200 due 5 Nov."""
    record(card, groceries, "1200", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    return Statement.objects.get()


def test_a_recorded_payment_withdraws_the_payment_draft(
    card: Account, billed: Statement
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))

    run_daily_job(date(2026, 11, 3))

    assert not Draft.objects.exists()
    billed.refresh_from_db()
    assert billed.transaction == payment


def test_a_payment_made_soon_after_the_statement_day_still_covers_it(
    card: Account, billed: Statement
) -> None:
    assert card.pays_from
    record(card.pays_from, card, "1200", date(2026, 10, 16))

    run_daily_job(date(2026, 10, 16))

    assert not Draft.objects.exists()


def test_a_payment_far_off_the_statement_amount_does_not_cover_it(
    card: Account, billed: Statement
) -> None:
    assert card.pays_from
    record(card.pays_from, card, "500", date(2026, 11, 3))

    run_daily_job(date(2026, 11, 3))

    assert Draft.objects.waiting().count() == 1


def test_a_payment_that_settled_a_statement_is_not_counted_in_the_next(
    card: Account, groceries: Account, billed: Statement
) -> None:
    assert card.pays_from
    record(card.pays_from, card, "1200", date(2026, 11, 3))
    record(card, groceries, "400", date(2026, 11, 1))

    run_daily_job(date(2026, 11, 16))

    assert Statement.objects.last().amount == Decimal(400)  # type: ignore[union-attr]


def test_posting_the_payment_draft_settles_the_statement(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    # Due well after today, so posting it is posting early.
    record(card, groceries, "1200", date(2098, 12, 20))
    run_daily_job(date(2099, 1, 16))

    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))

    statement = Statement.objects.get()
    assert statement.transaction
    assert statement.transaction.date == timezone.localdate()


def edit_url(statement: Statement) -> str:
    return reverse("statement_edit", args=[statement.pk])


def test_entering_the_actual_amount_replaces_the_estimate(
    signed_in: Client, billed: Statement
) -> None:
    response = signed_in.post(edit_url(billed), {"actual_amount": "1350.75"})

    assert response.status_code == 302
    billed.refresh_from_db()
    assert billed.amount == Decimal("1350.75")
    assert [split.amount for split in Draft.objects.get().splits.all()] == [
        Decimal("1350.75")
    ]


def test_clearing_the_actual_amount_goes_back_to_the_estimate(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(edit_url(billed), {"actual_amount": "1350.75"})

    signed_in.post(edit_url(billed), {"actual_amount": ""})

    assert [split.amount for split in Draft.objects.get().splits.all()] == [
        Decimal(1200)
    ]


def test_the_actual_amount_covers_a_payment_the_estimate_did_not(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    assert card.pays_from
    signed_in.post(edit_url(billed), {"actual_amount": "2000"})
    record(card.pays_from, card, "2000", date(2026, 11, 4))

    run_daily_job(date(2026, 11, 4))

    assert not Draft.objects.exists()


def test_an_actual_amount_proposes_a_payment_the_estimate_did_not(
    signed_in: Client, card: Account
) -> None:
    run_daily_job(date(2026, 10, 16))
    statement = Statement.objects.get()

    signed_in.post(edit_url(statement), {"actual_amount": "640"})

    draft = Draft.objects.get()
    assert (draft.date, draft.splits.get().amount) == (date(2026, 11, 5), Decimal(640))


def test_a_posted_payment_draft_is_left_alone(
    signed_in: Client, billed: Statement
) -> None:
    draft = Draft.objects.get()
    signed_in.post(reverse("draft_post", args=[draft.pk]))

    signed_in.post(edit_url(billed), {"actual_amount": "1350.75"})

    assert draft.splits.get().amount == Decimal(1200)
    assert Draft.objects.count() == 1


def test_a_negative_actual_amount_is_refused(
    signed_in: Client, billed: Statement
) -> None:
    response = signed_in.post(edit_url(billed), {"actual_amount": "-5"})

    assert response.status_code == 200
    billed.refresh_from_db()
    assert billed.actual_amount is None


def test_the_card_page_lists_its_statements(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    url = reverse("account_transactions", kwargs={"kind": "liability", "pk": card.pk})

    body = signed_in.get(url).content.decode()

    assert "Statements" in body
    assert "5 Nov 2026" in body
    assert edit_url(billed) in body


def test_an_unknown_statement_is_not_found(signed_in: Client) -> None:
    assert signed_in.get(reverse("statement_edit", args=[999])).status_code == 404


def test_a_payment_recorded_before_the_job_caught_up_means_no_draft(
    card: Account, groceries: Account
) -> None:
    assert card.pays_from
    record(card, groceries, "1200", date(2026, 9, 20))
    record(card.pays_from, card, "1200", date(2026, 10, 18))

    run_daily_job(date(2026, 10, 20))

    assert Statement.objects.get().transaction
    assert not Draft.objects.exists()


def test_the_drafts_list_shows_card_payments_apart(
    signed_in: Client, billed: Statement
) -> None:
    body = signed_in.get(reverse("draft_list")).content.decode()

    assert "Card payments" in body
    assert "HDFC card Statement to 15 Oct 2026" in body


def test_an_actual_amount_of_zero_withdraws_the_payment_draft(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(edit_url(billed), {"actual_amount": "0"})

    assert not Draft.objects.exists()


def test_a_positive_actual_amount_after_zero_proposes_the_payment_again(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(edit_url(billed), {"actual_amount": "0"})

    signed_in.post(edit_url(billed), {"actual_amount": "900"})

    assert Draft.objects.get().splits.get().amount == Decimal(900)


def test_deleting_the_payment_reopens_the_statement_and_proposes_it_again(
    card: Account, billed: Statement
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))
    run_daily_job(date(2026, 11, 3))

    payment.delete()

    billed.refresh_from_db()
    assert billed.transaction is None
    draft = Draft.objects.waiting().get()
    assert (draft.statement, draft.splits.get().amount) == (billed, Decimal(1200))


def test_deleting_a_posted_payment_proposes_it_again(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))
    payment = Statement.objects.get().transaction
    assert payment

    payment.delete()

    billed.refresh_from_db()
    assert billed.transaction is None
    assert Draft.objects.waiting().get().statement == billed


def test_deleting_the_payment_of_nothing_to_pay_proposes_no_draft(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))
    run_daily_job(date(2026, 11, 3))
    signed_in.post(edit_url(billed), {"actual_amount": "0"})

    payment.delete()

    billed.refresh_from_db()
    assert billed.transaction is None
    assert not Draft.objects.exists()
