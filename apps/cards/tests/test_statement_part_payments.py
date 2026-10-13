from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.cards.models import Statement
from apps.cards.statements import enter_actual_amount, link_payment, unlink_payment
from apps.cards.tests.conftest import record
from apps.cards.tests.test_card_payments import edit_url, link_url, unlink_url
from apps.digest.upcoming import card_due_days
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.transactions.models import Transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def big(card: Account, groceries: Account) -> Statement:
    """The card's Statement to 15 Oct 2026, of 10,000 due 5 Nov."""
    record(card, groceries, "10000", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    return Statement.objects.get()


def pay(card: Account, amount: str, on: date) -> Transaction:
    assert card.pays_from
    return record(card.pays_from, card, amount, on)


def waiting_amount(statement: Statement) -> Decimal:
    amount = Draft.objects.waiting().get(statement=statement).splits.get().amount
    assert amount is not None
    return amount


def november(card: Account, groceries: Account) -> Statement:
    """The next Statement, to 15 Nov, with 400 spent in its period."""
    record(card, groceries, "400", date(2026, 11, 1))
    run_daily_job(date(2026, 11, 16))
    return Statement.objects.get(period_end=date(2026, 11, 15))


def test_a_part_payment_leaves_the_statement_unpaid_and_proposes_the_rest(
    card: Account, groceries: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "5000", date(2026, 10, 25)))
    next_one = november(card, groceries)

    big.refresh_from_db()
    assert (big.is_paid, big.needs_payment, big.owed) == (False, True, Decimal(5000))
    assert waiting_amount(big) == Decimal(5000)
    assert big.amount == Decimal(10000)
    assert next_one.amount == Decimal(400)


def test_a_second_part_that_covers_it_pays_it_and_withdraws_the_draft(
    card: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "5000", date(2026, 10, 25)))

    link_payment(big, pay(card, "5000", date(2026, 11, 1)))

    big.refresh_from_db()
    assert big.is_paid
    assert big.payments.count() == 2
    assert not Draft.objects.filter(statement=big).exists()


def test_the_daily_match_links_a_payment_of_what_is_still_owed(
    card: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "4000", date(2026, 10, 20)))
    rest = pay(card, "6000", date(2026, 11, 3))

    run_daily_job(date(2026, 11, 3))

    big.refresh_from_db()
    assert big.is_paid
    assert rest in big.payments.all()
    assert not Draft.objects.filter(statement=big).exists()


def test_the_daily_match_leaves_a_smaller_part_for_the_user(
    card: Account, big: Statement
) -> None:
    pay(card, "4000", date(2026, 11, 3))

    run_daily_job(date(2026, 11, 3))

    assert not big.payments.exists()


@pytest.mark.usefixtures("late_today")
def test_an_actual_amount_above_what_was_paid_makes_it_unpaid_again(
    signed_in: Client, card: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "10000", date(2026, 10, 25)))
    assert not Draft.objects.exists()

    enter_actual_amount(big, Decimal(12000))

    big.refresh_from_db()
    assert not big.is_paid
    assert waiting_amount(big) == Decimal(2000)
    assert [item.amount for item in card_due_days(date(2026, 11, 2))] == [Decimal(2000)]
    home = page_text(signed_in.get(reverse("index")).content.decode())
    assert "₹2,000.00 overdue since 5 Nov" in home


@pytest.mark.usefixtures("late_today")
def test_unlinking_one_of_two_parts_makes_it_unpaid_and_counts_it_again(
    signed_in: Client, card: Account, groceries: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "5000", date(2026, 10, 25)))
    second = pay(card, "5000", date(2026, 11, 3))
    link_payment(big, second)
    next_one = november(card, groceries)

    signed_in.post(unlink_url(big), {"transaction": second.pk})

    big.refresh_from_db()
    next_one.refresh_from_db()
    assert not big.is_paid
    assert waiting_amount(big) == Decimal(5000)
    assert next_one.amount == Decimal(-4600)


def test_deleting_one_of_two_parts_makes_it_unpaid_and_counts_it_again(
    card: Account, groceries: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "5000", date(2026, 10, 25)))
    second = pay(card, "5000", date(2026, 11, 3))
    link_payment(big, second)
    next_one = november(card, groceries)
    third = pay(card, "100", date(2026, 10, 30))

    third.delete()
    second.delete()

    big.refresh_from_db()
    next_one.refresh_from_db()
    assert not big.is_paid
    assert waiting_amount(big) == Decimal(5000)
    assert next_one.amount == Decimal(400)


def test_unlinking_a_part_that_leaves_it_covered_keeps_it_paid(
    card: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "10000", date(2026, 10, 25)))
    extra = pay(card, "500", date(2026, 10, 26))
    link_payment(big, extra)

    unlink_payment(big, extra)

    big.refresh_from_db()
    assert big.is_paid
    assert not Draft.objects.exists()


def test_deleting_the_payment_its_draft_posted_proposes_what_is_still_owed(
    signed_in: Client, card: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "4000", date(2026, 10, 25)))
    draft = Draft.objects.get()
    signed_in.post(reverse("draft_post", args=[draft.pk]))
    assert Statement.objects.get().is_paid
    posted = Draft.objects.get().transaction
    assert posted

    posted.delete()

    big.refresh_from_db()
    assert not big.is_paid
    assert not Draft.objects.filter(pk=draft.pk).exists()
    assert waiting_amount(big) == Decimal(6000)


@pytest.mark.usefixtures("late_today")
def test_unlinking_the_payment_its_draft_posted_proposes_what_is_still_owed(
    signed_in: Client, big: Statement
) -> None:
    draft = Draft.objects.get()
    signed_in.post(reverse("draft_post", args=[draft.pk]))
    posted = Draft.objects.get().transaction
    assert posted

    unlink_payment(big, posted)

    assert not Draft.objects.filter(pk=draft.pk).exists()
    assert waiting_amount(big) == Decimal(10000)


def test_a_posted_draft_short_of_the_amount_proposes_no_second_one(
    signed_in: Client, big: Statement
) -> None:
    signed_in.post(reverse("draft_post", args=[Draft.objects.get().pk]))

    enter_actual_amount(big, Decimal(11000))

    big.refresh_from_db()
    assert big.owed == Decimal(1000)
    assert Draft.objects.get().status == Draft.Status.POSTED


@pytest.mark.usefixtures("late_today")
def test_the_statement_page_lists_every_part_and_offers_more_while_unpaid(
    signed_in: Client, card: Account, big: Statement
) -> None:
    first = pay(card, "3000", date(2026, 10, 25))
    second = pay(card, "2000", date(2026, 11, 3))
    pay(card, "700", date(2026, 11, 4))
    for payment in (first, second):
        signed_in.post(link_url(big), {"transaction": payment.pk})

    text = page_text(signed_in.get(edit_url(big)).content.decode())

    assert "Paid on 25 Oct 2026 ₹3,000.00" in text
    assert "Paid on 3 Nov 2026 ₹2,000.00" in text
    assert text.count("Not this payment") == 2
    assert "₹5,000.00 still owed" in text
    assert "Link payment" in text
    assert "₹700.00" in text


@pytest.mark.usefixtures("late_today")
def test_the_card_page_shows_the_last_payment_date(
    signed_in: Client, card: Account, big: Statement
) -> None:
    link_payment(big, pay(card, "6000", date(2026, 10, 25)))
    link_payment(big, pay(card, "4000", date(2026, 11, 3)))
    url = reverse("account_transactions", kwargs={"kind": "liability", "pk": card.pk})

    text = page_text(signed_in.get(url).content.decode())

    assert "Paid 3 Nov" in text
