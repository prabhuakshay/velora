from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.cards.models import Statement
from apps.cards.statements import enter_actual_amount, link_payment
from apps.cards.tests.conftest import make_card, record
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.tests.conftest import make_schedule
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_a_recorded_payment_withdraws_the_payment_draft(
    card: Account, billed: Statement
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))

    run_daily_job(date(2026, 11, 3))

    assert not Draft.objects.exists()
    billed.refresh_from_db()
    assert list(billed.payments.all()) == [payment]


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


def test_a_payment_that_paid_a_statement_is_not_counted_in_the_next(
    card: Account, groceries: Account, billed: Statement
) -> None:
    assert card.pays_from
    record(card.pays_from, card, "1200", date(2026, 11, 3))
    record(card, groceries, "400", date(2026, 11, 1))

    run_daily_job(date(2026, 11, 16))

    assert Statement.objects.last().amount == Decimal(400)  # type: ignore[union-attr]


def test_posting_the_payment_draft_pays_the_statement(
    signed_in: Client, card: Account, groceries: Account
) -> None:
    # Due well after today, so posting it is posting early.
    record(card, groceries, "1200", date(2098, 12, 20))
    run_daily_job(date(2099, 1, 16))

    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))

    statement = Statement.objects.get()
    assert statement.is_paid
    assert statement.payments.get().date == timezone.localdate()


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


def test_a_negative_actual_amount_is_a_credit(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(edit_url(billed), {"actual_amount": "-5"})

    billed.refresh_from_db()
    assert billed.actual_amount == Decimal(-5)
    assert not billed.needs_payment


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

    assert Statement.objects.get().is_paid
    assert not Draft.objects.exists()


def test_the_drafts_list_marks_card_payments(
    signed_in: Client, billed: Statement
) -> None:
    body = signed_in.get(reverse("draft_list")).content.decode()

    assert "Card payment" in body
    assert "HDFC card Statement to 15 Oct 2026" in body


def test_an_actual_amount_of_zero_withdraws_the_payment_draft(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(edit_url(billed), {"actual_amount": "0"})

    assert not Draft.objects.exists()


@pytest.mark.parametrize(
    ("estimated", "actual", "paid", "needs_payment"),
    [
        ("1200", None, False, True),
        ("0", None, False, False),
        ("-500", None, False, False),
        ("1200", None, True, False),
        ("1200", "0", False, False),
    ],
)
def test_a_statement_needs_payment_only_while_something_is_owed(
    card: Account,
    *,
    estimated: str,
    actual: str | None,
    paid: bool,
    needs_payment: bool,
) -> None:
    statement = Statement.objects.create(
        card=card,
        period_start=date(2026, 9, 16),
        period_end=date(2026, 10, 15),
        due_date=date(2026, 11, 5),
        estimated_amount=Decimal(estimated),
        actual_amount=None if actual is None else Decimal(actual),
    )
    if paid:
        assert card.pays_from
        payment = record(card.pays_from, card, estimated, date(2026, 11, 3))
        Transaction.objects.filter(pk=payment.pk).update(statement=statement)

    assert statement.needs_payment is needs_payment


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
    assert not billed.payments.exists()
    draft = Draft.objects.waiting().get()
    assert (draft.statement, draft.splits.get().amount) == (billed, Decimal(1200))


def test_deleting_a_posted_payment_proposes_it_again(
    signed_in: Client, billed: Statement
) -> None:
    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))
    payment = Statement.objects.get().payments.get()

    payment.delete()

    billed.refresh_from_db()
    assert not billed.payments.exists()
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
    assert not billed.payments.exists()
    assert not Draft.objects.exists()


def test_a_payment_draft_is_estimated_until_the_actual_amount_is_entered(
    billed: Statement,
) -> None:
    def draft() -> Draft:
        return Draft.objects.get()

    assert draft().estimated

    enter_actual_amount(billed, Decimal(1450))
    assert not draft().estimated
    assert [split.amount for split in draft().splits.all()] == [Decimal(1450)]

    enter_actual_amount(billed, None)
    assert draft().estimated


def link_url(statement: Statement) -> str:
    return reverse("statement_link_payment", args=[statement.pk])


def unlink_url(statement: Statement) -> str:
    return reverse("statement_unlink_payment", args=[statement.pk])


@pytest.mark.parametrize(
    ("amount", "on", "other_bank"),
    [
        ("1200", date(2026, 11, 2), True),
        ("1200", date(2026, 11, 20), False),
    ],
    ids=["second bank", "late"],
)
@pytest.mark.usefixtures("late_today")
def test_linking_a_payment_marks_the_statement_paid(  # noqa: PLR0913
    signed_in: Client,
    card: Account,
    billed: Statement,
    *,
    amount: str,
    on: date,
    other_bank: bool,
) -> None:
    source = make_account("ICICI savings", "asset") if other_bank else card.pays_from
    assert source
    payment = record(source, card, amount, on)
    run_daily_job(timezone.localdate())

    response = signed_in.post(link_url(billed), {"transaction": payment.pk})

    assert response["Location"] == edit_url(billed)
    billed.refresh_from_db()
    assert list(billed.payments.all()) == [payment]
    assert not Draft.objects.waiting().filter(statement=billed).exists()


def test_linking_a_payment_raises_the_next_estimate(
    signed_in: Client,
    card: Account,
    groceries: Account,
    billed: Statement,
    late_today: date,
) -> None:
    other_bank = make_account("ICICI savings", "asset")
    payment = record(other_bank, card, "1200", date(2026, 11, 2))
    record(card, groceries, "400", date(2026, 11, 1))
    run_daily_job(date(2026, 11, 16))
    november = Statement.objects.get(period_end=date(2026, 11, 15))
    assert november.amount == 0

    signed_in.post(link_url(billed), {"transaction": payment.pk})

    november.refresh_from_db()
    assert november.amount == Decimal(400)


def test_a_payment_linked_elsewhere_is_refused(
    signed_in: Client,
    card: Account,
    groceries: Account,
    billed: Statement,
    late_today: date,
) -> None:
    assert card.pays_from
    record(card, groceries, "500", date(2026, 10, 20))
    run_daily_job(date(2026, 11, 16))
    november = Statement.objects.get(period_end=date(2026, 11, 15))
    payment = record(card.pays_from, card, "500", date(2026, 11, 20))
    link_payment(november, payment)

    response = signed_in.post(link_url(billed), {"transaction": payment.pk})

    assert response["Location"] == edit_url(billed)
    billed.refresh_from_db()
    november.refresh_from_db()
    assert not billed.payments.exists()
    assert list(november.payments.all()) == [payment]
    assert (
        "Pick a payment into the card"
        in signed_in.get(edit_url(billed)).content.decode()
    )


@pytest.mark.usefixtures("late_today")
def test_payments_linked_to_an_occurrence_or_another_card_are_refused(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    assert card.pays_from
    scheduled = record(card.pays_from, card, "1200", date(2026, 11, 4))
    make_schedule((card.pays_from, card, "1200")).occurrences.create(
        due_date=date(2026, 11, 4), transaction=scheduled
    )
    elsewhere = record(card.pays_from, make_card("SBI card"), "1200", date(2026, 11, 4))

    for payment in (scheduled, elsewhere):
        signed_in.post(link_url(billed), {"transaction": payment.pk})

    billed.refresh_from_db()
    assert not billed.payments.exists()


@pytest.mark.usefixtures("late_today")
def test_a_paid_statement_refuses_another_payment(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    assert card.pays_from
    first = record(card.pays_from, card, "1200", date(2026, 11, 3))
    link_payment(billed, first)
    second = record(card.pays_from, card, "1200", date(2026, 11, 4))

    signed_in.post(link_url(billed), {"transaction": second.pk})

    billed.refresh_from_db()
    assert list(billed.payments.all()) == [first]


@pytest.mark.parametrize("pk", ["999", "", "x"])
def test_an_unknown_payment_is_refused(
    signed_in: Client, billed: Statement, late_today: date, pk: str
) -> None:
    response = signed_in.post(link_url(billed), {"transaction": pk})

    assert response["Location"] == edit_url(billed)
    billed.refresh_from_db()
    assert not billed.payments.exists()


def test_a_payment_dated_in_the_period_is_refused(
    signed_in: Client, card: Account, billed: Statement, late_today: date
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 10, 15))

    signed_in.post(link_url(billed), {"transaction": payment.pk})

    billed.refresh_from_db()
    assert not billed.payments.exists()


def test_unlinking_reopens_the_statement_and_proposes_its_payment(
    signed_in: Client,
    card: Account,
    groceries: Account,
    billed: Statement,
    late_today: date,
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))
    record(card, groceries, "400", date(2026, 11, 1))
    run_daily_job(date(2026, 11, 16))
    november = Statement.objects.get(period_end=date(2026, 11, 15))
    assert november.amount == Decimal(400)

    response = signed_in.post(unlink_url(billed), {"transaction": payment.pk})

    assert response["Location"] == edit_url(billed)
    billed.refresh_from_db()
    november.refresh_from_db()
    assert not billed.payments.exists()
    assert Transaction.objects.filter(pk=payment.pk).exists()
    assert Draft.objects.waiting().get(statement=billed).splits.get().amount == (
        Decimal(1200)
    )
    assert november.amount == 0


def test_unlinking_leaves_a_rejected_draft_rejected(
    signed_in: Client, card: Account, billed: Statement, late_today: date
) -> None:
    assert card.pays_from
    draft = Draft.objects.get()
    draft.status = Draft.Status.REJECTED
    draft.save()
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))
    link_payment(billed, payment)

    signed_in.post(unlink_url(billed), {"transaction": payment.pk})

    billed.refresh_from_db()
    assert not billed.payments.exists()
    assert list(Draft.objects.values_list("status", flat=True)) == [
        Draft.Status.REJECTED
    ]
