from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft
from apps.quick_add.tests.conftest import make_draft, make_manual_draft
from apps.transactions.models import Transaction
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_the_drafts_list_shows_a_missing_amount_as_unknown(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    dentist = make_account("Health", "expense")
    make_manual_draft((card, dentist, None), description="Dentist, pay later")
    make_draft((card, dentist, "850"))

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert "Dentist, pay later" in body
    assert "₹?" in body
    assert "₹850.00" in body


def test_privacy_mode_masks_draft_amounts(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    dentist = make_account("Health", "expense")
    make_manual_draft((card, dentist, None))
    make_draft((card, dentist, "850"))
    turn_on(signed_in)

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert "₹850.00" not in body
    assert "Amount hidden" in body


def post(client: Client, draft: Draft) -> str:
    response = client.post(reverse("draft_post", args=[draft.pk]), follow=True)
    return response.content.decode()


@pytest.mark.parametrize(
    ("gap", "reason"),
    [
        ((True, True, False), "Split 1: missing amount."),
        ((False, True, True), "Split 1: missing From Account."),
        ((True, False, True), "Split 1: missing To Account."),
    ],
)
def test_posting_a_draft_with_a_gap_names_what_is_missing(
    signed_in: Client, gap: tuple[bool, bool, bool], reason: str
) -> None:
    card = make_account("HDFC Card", "liability")
    dentist = make_account("Health", "expense")
    has_from, has_to, has_amount = gap
    draft = make_manual_draft(
        (
            card if has_from else None,
            dentist if has_to else None,
            "850" if has_amount else None,
        )
    )

    body = post(signed_in, draft)

    assert f"Couldn't post: {reason}" in body
    assert "Enter a number" not in body
    assert not Transaction.objects.exists()
    draft.refresh_from_db()
    assert draft.status == Draft.Status.WAITING


def test_posting_a_draft_without_splits_is_refused(signed_in: Client) -> None:
    draft = make_manual_draft()

    body = post(signed_in, draft)

    assert "Couldn't post: Add at least one Split." in body
    assert not Transaction.objects.exists()


def test_an_amountless_quick_add_draft_is_refused_too(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    dentist = make_account("Health", "expense")
    quick_add = make_draft((card, dentist, None))

    body = post(signed_in, quick_add.draft)

    assert "Couldn't post: Split 1: missing amount." in body
    assert not Transaction.objects.exists()


def test_editing_fills_in_the_amount_and_posts_it(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    dentist = make_account("Health", "expense")
    draft = make_manual_draft((card, dentist, None), description="Dentist")
    url = reverse("draft_edit", args=[draft.pk])

    form = signed_in.get(url).content.decode()
    assert "Enter a number" not in form
    signed_in.post(
        url,
        {
            "date": "2026-10-08",
            "party": "",
            "description": "Dentist",
            "splits-TOTAL_FORMS": 1,
            "splits-INITIAL_FORMS": 0,
            "splits-0-from_account": card.pk,
            "splits-0-to_account": dentist.pk,
            "splits-0-amount": "1200",
        },
    )

    transaction = Transaction.objects.get()
    assert transaction.date == date(2026, 10, 8)
    assert transaction.splits.get().amount == Decimal("1200.00")
    draft.refresh_from_db()
    assert draft.status == Draft.Status.POSTED


def test_a_draft_dated_after_today_posts_on_today(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    rent = make_account("Rent", "expense")
    today = timezone.localdate()
    draft = make_manual_draft((card, rent, "25000"), date=today + timedelta(days=3))

    post(signed_in, draft)

    assert Transaction.objects.get().date == today


def test_editing_a_draft_dated_after_today_starts_from_today(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    rent = make_account("Rent", "expense")
    today = timezone.localdate()
    draft = make_manual_draft((card, rent, "25000"), date=today + timedelta(days=3))

    form = signed_in.get(reverse("draft_edit", args=[draft.pk])).content.decode()

    assert f'value="{today.isoformat()}"' in form
    assert "cannot be after today" not in form
