from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.quick_add.tests.conftest import make_draft, make_manual_draft
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_a_draft_is_started_by_hand(signed_in: Client) -> None:
    dentist = Party.objects.create(name="Smile Dental")

    response = signed_in.post(
        reverse("draft_create"),
        {"date": "2026-10-12", "party": dentist.pk, "description": "Pay later"},
    )

    assert response["Location"] == reverse("draft_list")
    draft = Draft.objects.get()
    assert (draft.source, draft.date, draft.party, draft.description) == (
        Draft.Source.MANUAL,
        date(2026, 10, 12),
        dentist,
        "Pay later",
    )
    assert draft.status == Draft.Status.WAITING


def test_the_form_dates_a_new_draft_today_and_needs_nothing_else(
    signed_in: Client,
) -> None:
    form = signed_in.get(reverse("draft_create")).content.decode()

    assert f'value="{timezone.localdate().isoformat()}"' in form
    signed_in.post(reverse("draft_create"), {"date": "2026-10-12"})
    assert Draft.objects.get().source == Draft.Source.MANUAL


def test_starting_a_draft_needs_sign_in(client: Client) -> None:
    response = client.post(reverse("draft_create"), {"date": "2026-10-12"})

    assert response["Location"].startswith(reverse("login"))
    assert not Draft.objects.exists()


def test_the_drafts_page_offers_a_new_draft(signed_in: Client) -> None:
    body = signed_in.get(reverse("draft_list")).content.decode()

    assert reverse("draft_create") in body


def test_the_drafts_page_separates_drafts_by_source(signed_in: Client) -> None:
    make_manual_draft(description="Dentist, pay later")
    make_draft(text="lunch at Toit 850", description="Team lunch")
    Draft.objects.create(
        source=Draft.Source.SCHEDULE, date=date(2026, 10, 1), description="Rent"
    )

    body = signed_in.get(reverse("draft_list")).content.decode()

    order = [
        "From Quick Add",
        "Team lunch",
        "From Schedules",
        "Rent",
        "Started by hand",
        "Dentist, pay later",
    ]
    positions = [body.index(text) for text in order]
    assert positions == sorted(positions)


def test_a_source_with_no_waiting_drafts_shows_no_heading(signed_in: Client) -> None:
    make_manual_draft(description="Dentist")

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert "Started by hand" in body
    assert "From Quick Add" not in body
    assert "From Schedules" not in body


def test_a_hand_made_draft_posts_to_a_transaction(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    health = make_account("Health", "expense")
    draft = make_manual_draft((card, health, "1500"), description="Dentist")

    signed_in.post(reverse("draft_post", args=[draft.pk]))

    transaction = Transaction.objects.get()
    assert transaction.description == "Dentist"
    assert [
        (s.from_account, s.to_account, s.amount) for s in transaction.splits.all()
    ] == [(card, health, Decimal(1500))]
    draft.refresh_from_db()
    assert (draft.status, draft.transaction) == (Draft.Status.POSTED, transaction)


def test_posting_an_unfinished_hand_made_draft_is_refused_with_a_reason(
    signed_in: Client,
) -> None:
    draft = make_manual_draft(description="Dentist")

    response = signed_in.post(reverse("draft_post", args=[draft.pk]), follow=True)

    assert "Couldn't post: " in response.content.decode()
    assert not Transaction.objects.exists()
    draft.refresh_from_db()
    assert draft.status == Draft.Status.WAITING


def test_editing_a_hand_made_draft_posts_it_with_the_edits(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    health = make_account("Health", "expense")
    draft = make_manual_draft(description="Dentist")

    form = signed_in.get(reverse("draft_edit", args=[draft.pk])).content.decode()
    response = signed_in.post(
        reverse("draft_edit", args=[draft.pk]),
        {
            "action": "post",
            "date": "2026-10-08",
            "description": "Dentist, filling",
            "splits-TOTAL_FORMS": 1,
            "splits-INITIAL_FORMS": 0,
            "splits-0-from_account": card.pk,
            "splits-0-to_account": health.pk,
            "splits-0-amount": "2400",
        },
    )

    assert "Dentist" in form
    assert response["Location"] == reverse("draft_list")
    transaction = Transaction.objects.get()
    assert transaction.description == "Dentist, filling"
    assert transaction.splits.get().amount == Decimal(2400)
    draft.refresh_from_db()
    assert (draft.status, draft.transaction) == (Draft.Status.POSTED, transaction)


def test_rejecting_a_hand_made_draft_keeps_it_off_the_drafts_page(
    signed_in: Client,
) -> None:
    draft = make_manual_draft(description="Dentist")

    signed_in.post(reverse("draft_reject", args=[draft.pk]))

    draft.refresh_from_db()
    assert draft.status == Draft.Status.REJECTED
    assert "Dentist" not in signed_in.get(reverse("draft_list")).content.decode()
    assert not Transaction.objects.exists()
