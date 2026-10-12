from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.cards.models import Statement
from apps.cards.tests.conftest import record
from apps.cards.tests.test_card_payments import edit_url
from apps.cards.tests.test_statement_estimate_refresh import record_via_form
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_the_statement_page_breaks_down_its_estimate(
    signed_in: Client, card: Account, groceries: Account, billed: Statement
) -> None:
    record(groceries, card, "200", date(2026, 10, 1))

    page = signed_in.get(edit_url(billed)).content.decode()

    text = page_text(page)
    assert "Spent on the card ₹1,200.00" in text
    assert "Payments and refunds -₹200.00" in text
    assert "Comes to ₹1,000.00" in text
    assert reverse("draft_edit", args=[Draft.objects.get().pk]) in page
    assert f"account={card.pk}&start=2026-09-16&end=2026-10-15" in page


def test_the_statement_page_steps_to_older_and_newer_statements(
    signed_in: Client, card: Account, groceries: Account, billed: Statement
) -> None:
    record(card, groceries, "300", date(2026, 10, 20))
    run_daily_job(date(2026, 11, 16))
    newer = Statement.objects.get(period_end=date(2026, 11, 15))

    older_page = signed_in.get(edit_url(billed)).content.decode()
    newer_page = signed_in.get(edit_url(newer)).content.decode()

    assert edit_url(newer) in older_page
    assert edit_url(billed) in newer_page


def test_a_paid_statement_links_its_payment(
    signed_in: Client, card: Account, billed: Statement
) -> None:
    assert card.pays_from
    payment = record(card.pays_from, card, "1200", date(2026, 11, 3))
    run_daily_job(date(2026, 11, 3))

    page = signed_in.get(edit_url(billed)).content.decode()

    assert "Paid on" in page_text(page)
    assert reverse("transaction_edit", args=[payment.pk]) in page


def test_the_headline_matches_the_breakdown_after_a_late_transaction(
    signed_in: Client, card: Account, groceries: Account, billed: Statement
) -> None:
    record_via_form(signed_in, card, groceries, amount="400", date="2026-10-10")

    text = page_text(signed_in.get(edit_url(billed)).content.decode())

    assert "₹1,600.00 Estimated from the Transactions" in text
    assert "Comes to ₹1,600.00" in text
