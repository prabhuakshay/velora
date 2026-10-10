from datetime import date, timedelta
from decimal import Decimal
from html import unescape
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party, Tag
from apps.quick_add.models import Draft, QuickAdd
from apps.quick_add.tests.conftest import make_draft, make_manual_draft
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms
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
    quick_add = make_draft(
        (card, food, "850"),
        (card, fun, "150.50"),
        party=toit,
        description="Team lunch",
    )

    response = signed_in.get(reverse("draft_edit", args=[quick_add.draft.pk]))

    form = response.context["form"]
    assert str(form["date"].value()) == date(2026, 10, 8).isoformat()
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


def first_split(draft: Draft) -> dict[str, Any]:
    """The edit form's fields that keep the Draft's first Split as a row."""
    return {"splits-INITIAL_FORMS": "1", "splits-0-id": draft.splits.get().pk}


def edited(**fields: Any) -> dict[str, Any]:
    """The submitted Draft edit form with one Split; Save and post by default."""
    return {
        "action": "post",
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
    quick_add = make_draft((card, food, "850"))

    response = signed_in.post(
        reverse("draft_edit", args=[quick_add.draft.pk]),
        edited(
            description="Team lunch",
            attachments=upload("bill.pdf", b"%PDF-1.4 bill"),
            **first_split(quick_add.draft),
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
    quick_add.refresh_from_db()
    assert quick_add.status == QuickAdd.Status.POSTED
    assert quick_add.draft.transaction == transaction
    assert not quick_add.posted_without_edits


def test_invalid_form_is_shown_again_without_posting(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))

    response = signed_in.post(
        reverse("draft_edit", args=[quick_add.draft.pk]),
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
    quick_add.refresh_from_db()
    assert quick_add.status == QuickAdd.Status.DRAFT


def test_new_party_name_is_offered_and_created_on_save(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "1200"), new_party_name="Brik Oven")

    page = signed_in.get(reverse("draft_edit", args=[quick_add.draft.pk]))
    assert not page.context["form"]["party"].value()
    assert page.context["new_party"]["new_party_name"].value() == "Brik Oven"
    assert not Party.objects.exists()

    signed_in.post(
        reverse("draft_edit", args=[quick_add.draft.pk]),
        edited(
            new_party_name="Brik Oven",
            **first_split(quick_add.draft),
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": food.pk,
                "splits-0-amount": "1200",
            },
        ),
    )

    assert Transaction.objects.get().party == Party.objects.get(name="Brik Oven")


def test_a_draft_posted_meanwhile_is_not_posted_again(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "1200"), new_party_name="Brik Oven")
    is_valid = TransactionForms.is_valid

    def posted_by_another_request(forms: TransactionForms) -> bool:
        Draft.objects.filter(pk=quick_add.draft.pk).update(status=Draft.Status.POSTED)
        return is_valid(forms)

    monkeypatch.setattr(TransactionForms, "is_valid", posted_by_another_request)

    response = signed_in.post(
        reverse("draft_edit", args=[quick_add.draft.pk]),
        edited(
            new_party_name="Brik Oven",
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": food.pk,
                "splits-0-amount": "1200",
            },
        ),
    )

    assert response["Location"] == reverse("draft_list")
    assert not Transaction.objects.exists()
    assert not Party.objects.exists()


def test_new_party_name_matching_a_party_picks_it(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    quick_add = make_draft((card, food, "850"), new_party_name="toit brewpub")

    page = signed_in.get(reverse("draft_edit", args=[quick_add.draft.pk]))

    assert str(page.context["form"]["party"].value()) == str(toit.pk)
    assert page.context["new_party"]["new_party_name"].value() == ""


def test_draft_that_no_longer_passes_shows_why_on_edit(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))
    food.hidden = True
    food.save()

    page = signed_in.get(reverse("draft_edit", args=[quick_add.draft.pk]))

    assert "That Account is inactive or no longer exists." in page.content.decode()


def test_edit_is_offered_for_every_draft(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))
    failed = make_draft((card, food, "900"))
    failed.draft.posting_error = "Split 1 From: gone"
    failed.draft.save()

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert reverse("draft_edit", args=[quick_add.draft.pk]) in body
    assert reverse("draft_edit", args=[failed.draft.pk]) in body


def test_a_quick_add_draft_can_still_be_edited_without_a_key(
    signed_in: Client, settings: Any
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))
    settings.OPENROUTER_API_KEY = ""

    response = signed_in.get(reverse("draft_edit", args=[quick_add.draft.pk]))

    assert response.status_code == 200


def test_the_edit_page_offers_save_draft_and_save_and_post(signed_in: Client) -> None:
    draft = make_manual_draft(description="Dentist")

    body = signed_in.get(reverse("draft_edit", args=[draft.pk])).content.decode()

    assert 'name="action" value="save"' in body
    assert "Save Draft" in body
    assert 'name="action" value="post"' in body
    assert "Save and post" in body


def test_save_draft_keeps_the_edits_on_the_waiting_draft(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    fun = make_account("Fun", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    quick_add = make_draft((card, food, "850"), (card, fun, "150"), party=toit)
    first, second = quick_add.draft.splits.all()

    response = signed_in.post(
        reverse("draft_edit", args=[quick_add.draft.pk]),
        edited(
            action="save",
            date="2026-10-20",
            description="Team lunch, bill to come",
            **{
                "splits-TOTAL_FORMS": "3",
                "splits-INITIAL_FORMS": "2",
                "splits-0-id": first.pk,
                "splits-0-from_account": card.pk,
                "splits-0-to_account": food.pk,
                "splits-0-amount": "",
                "splits-1-id": second.pk,
                "splits-1-from_account": card.pk,
                "splits-1-to_account": fun.pk,
                "splits-1-amount": "150",
                "splits-1-DELETE": "on",
                "splits-2-from_account": "",
                "splits-2-to_account": "",
                "splits-2-amount": "40",
            },
        ),
    )

    assert response["Location"] == reverse("draft_list")
    assert not Transaction.objects.exists()
    draft = Draft.objects.get()
    assert (draft.status, draft.date, draft.party, draft.description) == (
        Draft.Status.WAITING,
        date(2026, 10, 20),
        None,
        "Team lunch, bill to come",
    )
    assert [(s.from_account, s.to_account, s.amount) for s in draft.splits.all()] == [
        (card, food, None),
        (None, None, Decimal(40)),
    ]
    assert QuickAdd.objects.get().status == QuickAdd.Status.DRAFT


def test_save_draft_keeps_a_new_party_name(signed_in: Client) -> None:
    draft = make_manual_draft(description="Dentist")

    signed_in.post(
        reverse("draft_edit", args=[draft.pk]),
        edited(
            action="save", new_party_name="Smile Dental", **{"splits-TOTAL_FORMS": "0"}
        ),
    )

    draft.refresh_from_db()
    assert draft.new_party_name == "Smile Dental"
    assert not Party.objects.exists()


def test_save_and_post_with_a_gap_saves_the_edits_and_says_why(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    health = make_account("Health", "expense")
    draft = make_manual_draft(description="Dentist")

    response = signed_in.post(
        reverse("draft_edit", args=[draft.pk]),
        edited(
            description="Dentist, filling",
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": health.pk,
                "splits-0-amount": "",
            },
        ),
    )

    assert response.status_code == 200
    body = unescape(response.content.decode())
    assert "Couldn't post: Split 1: missing amount." in body
    assert not Transaction.objects.exists()
    draft.refresh_from_db()
    assert draft.status == Draft.Status.WAITING
    assert draft.description == "Dentist, filling"
    assert draft.posting_error == "Split 1: missing amount."
    assert [(s.from_account, s.amount) for s in draft.splits.all()] == [(card, None)]


def test_save_and_post_breaking_a_rule_saves_the_edits_and_says_why(
    signed_in: Client,
) -> None:
    bank = make_account("Bank", "asset")
    salary = make_account("Salary", "income")
    draft = make_manual_draft()

    response = signed_in.post(
        reverse("draft_edit", args=[draft.pk]),
        edited(
            **{
                "splits-0-from_account": bank.pk,
                "splits-0-to_account": salary.pk,
                "splits-0-amount": "100",
            },
        ),
    )

    assert "An Income Account can only be a source." in response.content.decode()
    assert not Transaction.objects.exists()
    assert Draft.objects.get().splits.get().to_account == salary


def test_save_and_post_records_a_draft_dated_after_today_today(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    rent = make_account("Rent", "expense")
    today = timezone.localdate()
    draft = make_manual_draft((card, rent, "25000"))
    later = today + timedelta(days=3)

    page = signed_in.get(reverse("draft_edit", args=[draft.pk])).content.decode()
    signed_in.post(
        reverse("draft_edit", args=[draft.pk]),
        edited(
            date=later.isoformat(),
            **{
                "splits-0-from_account": card.pk,
                "splits-0-to_account": rent.pk,
                "splits-0-amount": "25000",
            },
        ),
    )

    assert "cannot be after today" not in page
    assert Transaction.objects.get().date == today
