from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party, Tag
from apps.quick_add.models import QuickAdd
from apps.quick_add.tests.conftest import make_draft
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import upload

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_edit_opens_the_transaction_form_filled_from_the_draft(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    fun = make_account("Fun", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    note = make_draft(
        (card, food, "850"),
        (card, fun, "150.50"),
        party=toit,
        description="Team lunch",
    )

    response = signed_in.get(reverse("draft_edit", args=[note.pk]))

    form = response.context["form"]
    assert form["date"].value() == date(2026, 10, 8).isoformat()
    assert str(form["party"].value()) == str(toit.pk)
    assert form["description"].value() == "Team lunch"
    assert [
        (
            str(split["from_account"].value()),
            str(split["to_account"].value()),
            str(split["amount"].value()),
        )
        for split in response.context["formset"]
    ] == [
        (str(card.pk), str(food.pk), "850.00"),
        (str(card.pk), str(fun.pk), "150.50"),
    ]


def edited(**fields: Any) -> dict[str, Any]:
    """A submitted Transaction form with one Split, as the user saved it."""
    return {
        "date": "2026-10-07",
        "party": "",
        "description": "",
        "new_party_name": "",
        "splits-TOTAL_FORMS": "1",
        "splits-INITIAL_FORMS": "0",
        **fields,
    }


def test_saving_the_form_posts_the_draft_with_edits(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    office = Tag.objects.create(name="Office")
    note = make_draft((card, food, "850"))

    response = signed_in.post(
        reverse("draft_edit", args=[note.pk]),
        edited(
            description="Team lunch",
            attachments=upload("bill.pdf", b"%PDF-1.4 bill"),
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": food.pk,
                "splits-0-amount": "900",
                "splits-0-tags": [office.pk],
            },
        ),
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("draft_list")
    transaction = Transaction.objects.get()
    assert (transaction.date, transaction.description) == (
        date(2026, 10, 7),
        "Team lunch",
    )
    split = transaction.splits.get()
    assert (split.amount, list(split.tags.all())) == (Decimal("900.00"), [office])
    assert [a.original_name for a in transaction.attachments.all()] == ["bill.pdf"]
    note.refresh_from_db()
    assert note.status == QuickAdd.Status.POSTED
    assert note.transaction == transaction
    assert not note.posted_without_edits


def test_invalid_form_is_shown_again_without_posting(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))

    response = signed_in.post(
        reverse("draft_edit", args=[note.pk]),
        edited(
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": food.pk,
                "splits-0-amount": "-5",
            }
        ),
    )

    assert response.status_code == 200
    assert response.context["formset"].forms[0].errors
    assert not Transaction.objects.exists()
    note.refresh_from_db()
    assert note.status == QuickAdd.Status.DRAFT


def test_new_party_name_is_offered_and_created_on_save(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "1200"), new_party_name="Brik Oven")

    page = signed_in.get(reverse("draft_edit", args=[note.pk]))
    assert page.context["form"]["party"].value() == ""
    assert page.context["new_party"]["new_party_name"].value() == "Brik Oven"
    assert not Party.objects.exists()

    signed_in.post(
        reverse("draft_edit", args=[note.pk]),
        edited(
            new_party_name="Brik Oven",
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": food.pk,
                "splits-0-amount": "1200",
            },
        ),
    )

    assert Transaction.objects.get().party == Party.objects.get(name="Brik Oven")


def test_new_party_name_matching_a_party_picks_it(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    note = make_draft((card, food, "850"), new_party_name="toit brewpub")

    page = signed_in.get(reverse("draft_edit", args=[note.pk]))

    assert str(page.context["form"]["party"].value()) == str(toit.pk)
    assert page.context["new_party"]["new_party_name"].value() == ""


def test_draft_that_no_longer_passes_shows_why_on_edit(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))
    food.hidden = True
    food.save()

    page = signed_in.get(reverse("draft_edit", args=[note.pk]))

    assert "That Account is inactive or no longer exists." in page.content.decode()


def test_edit_is_offered_for_every_draft(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))
    failed = make_draft((card, food, "900"))
    failed.failure_reason = "Split 1 From: gone"
    failed.save()

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert reverse("draft_edit", args=[note.pk]) in body
    assert reverse("draft_edit", args=[failed.pk]) in body


def test_edit_is_hidden_without_a_key(signed_in: Client, settings: Any) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))
    settings.OPENROUTER_API_KEY = ""

    response = signed_in.get(reverse("draft_edit", args=[note.pk]))

    assert response.status_code == 404
