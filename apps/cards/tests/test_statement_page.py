from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account, page_text
from apps.cards.models import Statement
from apps.cards.tests.conftest import record
from apps.cards.tests.test_card_payments import edit_url, link_url, unlink_url
from apps.cards.tests.test_statement_estimate_refresh import record_via_form
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.tests.conftest import make_schedule
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from collections.abc import Callable

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


def test_an_unpaid_statement_offers_payments_into_the_card(
    signed_in: Client,
    card: Account,
    groceries: Account,
    billed: Statement,
    late_today: date,
) -> None:
    assert card.pays_from
    other_bank = make_account("ICICI savings", "asset")
    record(card.pays_from, card, "600", date(2026, 11, 20))
    record(other_bank, card, "1200", date(2026, 11, 2))
    record(card.pays_from, card, "300", date(2026, 10, 15))
    record(groceries, card, "50", date(2026, 11, 1))
    record(card.pays_from, card, "700", date(2026, 11, 26))
    mixed = record(card.pays_from, card, "900", date(2026, 11, 10))
    mixed.splits.create(from_account=card, to_account=groceries, amount=Decimal(90))
    Statement.objects.create(
        card=card,
        period_start=date(2026, 10, 16),
        period_end=date(2026, 11, 15),
        due_date=date(2026, 12, 5),
        estimated_amount=Decimal(0),
        transaction=record(card.pays_from, card, "400", date(2026, 11, 22)),
    )
    scheduled = record(card.pays_from, card, "800", date(2026, 11, 4))
    make_schedule((card.pays_from, card, "800")).occurrences.create(
        due_date=date(2026, 11, 4), transaction=scheduled
    )

    page = page_text(signed_in.get(edit_url(billed)).content.decode())

    text = page[page.index("Link payment") : page.index("How it's estimated")]
    assert "ICICI savings ₹1,200.00" in text
    assert text.index("2 Nov 2026") < text.index("20 Nov 2026")
    assert "HDFC card bank ₹600.00" in text
    assert "HDFC card bank ₹900.00" in text
    for left_out in ("₹300.00", "₹50.00", "₹700.00", "₹800.00", "₹400.00", "₹990.00"):
        assert left_out not in text


def test_a_linked_payment_shows_as_paid_on_the_page_and_home(
    signed_in: Client,
    card: Account,
    billed: Statement,
    late_today: date,
) -> None:
    other_bank = make_account("ICICI savings", "asset")
    payment = record(other_bank, card, "1200", date(2026, 11, 2))

    signed_in.post(link_url(billed), {"transaction": payment.pk})

    page = signed_in.get(edit_url(billed)).content.decode()
    assert "Paid on 2 Nov 2026" in page_text(page)
    assert reverse("transaction_edit", args=[payment.pk]) in page
    assert "Not this payment" in page_text(page)
    assert "Link payment" not in page_text(page)
    assert "Statement paid" in signed_in.get(reverse("index")).content.decode()


@pytest.mark.parametrize("refund", [None, "500"])
def test_a_statement_with_nothing_to_pay_is_never_overdue(
    signed_in: Client,
    card: Account,
    groceries: Account,
    late_today: date,
    refund: str | None,
) -> None:
    if refund:
        record(groceries, card, refund, date(2026, 10, 1))
    run_daily_job(date(2026, 10, 16))

    page = page_text(signed_in.get(edit_url(Statement.objects.get())).content.decode())
    home = page_text(signed_in.get(reverse("index")).content.decode())

    assert "Nothing to pay" in page
    assert "Overdue" not in page
    assert "Due in" not in page
    assert "Nothing to pay" in home
    assert "overdue" not in home


@pytest.mark.parametrize(
    ("spent", "page_status", "home_status"),
    [
        (None, "Nothing to pay", "Nothing to pay"),
        ("1200", "Due in", "₹1,200.00 due 5 Nov"),
    ],
)
def test_before_its_due_date_a_statement_shows_whether_it_needs_paying(  # noqa: PLR0913
    signed_in: Client,
    card: Account,
    groceries: Account,
    monkeypatch: pytest.MonkeyPatch,
    *,
    spent: str | None,
    page_status: str,
    home_status: str,
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda *_a, **_k: date(2026, 11, 1))
    if spent:
        record(card, groceries, spent, date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))

    page = page_text(signed_in.get(edit_url(Statement.objects.get())).content.decode())
    home = page_text(signed_in.get(reverse("index")).content.decode())

    assert page_status in page
    assert home_status in home
    assert "verdue" not in page + home


def test_an_actual_amount_switches_an_overdue_statement_to_nothing_to_pay_and_back(
    signed_in: Client, billed: Statement, late_today: date
) -> None:
    def shown() -> tuple[str, str]:
        page = page_text(signed_in.get(edit_url(billed)).content.decode())
        home = page_text(signed_in.get(reverse("index")).content.decode())
        return page, home

    signed_in.post(edit_url(billed), {"actual_amount": "0"})
    page, home = shown()
    assert "Nothing to pay" in page
    assert "Overdue" not in page
    assert "Nothing to pay" in home
    assert "overdue" not in home

    signed_in.post(edit_url(billed), {"actual_amount": "900"})
    page, home = shown()
    assert "Overdue" in page
    assert "Nothing to pay" not in page
    assert "₹900.00 overdue since 5 Nov" in home


@pytest.mark.parametrize("url", [link_url, unlink_url])
def test_linking_and_unlinking_need_sign_in(
    client: Client, billed: Statement, url: Callable[[Statement], str]
) -> None:
    response = client.post(url(billed))

    assert response["Location"].startswith(reverse("login"))


@pytest.mark.parametrize("url", [link_url, unlink_url])
def test_linking_and_unlinking_are_blocked_in_privacy_mode(
    signed_in: Client, billed: Statement, url: Callable[[Statement], str]
) -> None:
    turn_on(signed_in)

    response = signed_in.post(url(billed))

    assert response["Location"] == privacy_mode_off_url(url(billed))


@pytest.mark.parametrize("url", [link_url, unlink_url])
def test_linking_and_unlinking_reject_get(
    signed_in: Client, billed: Statement, url: Callable[[Statement], str]
) -> None:
    assert signed_in.get(url(billed)).status_code == 405
