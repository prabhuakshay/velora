from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft, QuickAdd
from apps.quick_add.tests.conftest import (
    make_draft,
    make_manual_draft,
    make_quick_add,
)

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings

pytestmark = pytest.mark.django_db


def page(client: Client, name: str) -> str:
    return client.get(reverse(name), follow=True).content.decode()


def test_submitting_saves_it_as_processing_and_queues_it(signed_in: Client) -> None:
    response = signed_in.post(
        reverse("quick_add_create"), {"text": "lunch at Toit 850 on hdfc card"}
    )

    assert response["Location"] == reverse("draft_list")
    quick_add = QuickAdd.objects.get()
    assert (quick_add.text, quick_add.status) == (
        "lunch at Toit 850 on hdfc card",
        QuickAdd.Status.PROCESSING,
    )
    job = ProcrastinateJob.objects.get()
    assert job.args == {"quick_add_id": quick_add.pk}


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_quick_add_is_rejected_with_a_message(
    signed_in: Client, text: str
) -> None:
    response = signed_in.post(reverse("quick_add_create"), {"text": text}, follow=True)

    assert response.redirect_chain == [(reverse("transaction_list"), 302)]
    assert "Write what happened" in response.content.decode()
    assert not QuickAdd.objects.exists()
    assert not ProcrastinateJob.objects.exists()


def test_a_quick_add_over_500_characters_is_rejected(signed_in: Client) -> None:
    response = signed_in.post(
        reverse("quick_add_create"), {"text": "x" * 501}, follow=True
    )

    assert "at most 500 characters" in response.content.decode()
    assert not QuickAdd.objects.exists()


def test_a_quick_add_of_500_characters_is_kept(signed_in: Client) -> None:
    signed_in.post(reverse("quick_add_create"), {"text": "x" * 500})

    assert QuickAdd.objects.get().text == "x" * 500


def test_transactions_list_has_the_quick_add_box(signed_in: Client) -> None:
    body = page(signed_in, "transaction_list")

    assert reverse("quick_add_create") in body
    assert 'maxlength="500"' in body


def test_drafts_page_shows_the_draft_beside_the_text(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    quick_add = make_quick_add()
    quick_add.status = QuickAdd.Status.DRAFT
    quick_add.save()
    draft = Draft.objects.create(
        source=Draft.Source.QUICK_ADD,
        quick_add=quick_add,
        date="2026-10-08",
        party=toit,
        description="Team lunch",
    )
    draft.splits.create(from_account=card, to_account=food, amount=Decimal(850))

    body = page(signed_in, "draft_list")

    for text in [
        "lunch at Toit 850 on hdfc card",
        "8 Oct 2026",
        "Toit Brewpub",
        "Team lunch",
        "HDFC Card",
        "Eating Out",
        "₹850.00",
    ]:
        assert text in body


def test_drafts_page_names_a_new_party(signed_in: Client) -> None:
    quick_add = make_quick_add("dinner at Brik Oven 1200")
    quick_add.status = QuickAdd.Status.DRAFT
    quick_add.save()
    Draft.objects.create(
        source=Draft.Source.QUICK_ADD,
        quick_add=quick_add,
        date="2026-10-08",
        new_party_name="Brik Oven",
    )

    body = page(signed_in, "draft_list")

    assert "Brik Oven" in body
    assert "new Party" in body


def test_drafts_page_lists_only_quick_adds_that_need_the_user(
    signed_in: Client,
) -> None:
    for status in QuickAdd.Status:
        if status == QuickAdd.Status.DRAFT:
            make_draft(text="text draft")
        else:
            QuickAdd.objects.create(text=f"text {status}", status=status)

    body = page(signed_in, "draft_list")

    for shown in ["processing", "draft", "failed"]:
        assert f"text {shown}" in body
    for hidden in ["posted", "rejected"]:
        assert f"text {hidden}" not in body


def test_drafts_page_refreshes_itself_only_while_processing(
    signed_in: Client,
) -> None:
    quick_add = make_quick_add()

    assert 'hx-trigger="every' in page(signed_in, "draft_list")

    quick_add.status = QuickAdd.Status.FAILED
    quick_add.save()

    assert 'hx-trigger="every' not in page(signed_in, "draft_list")


def test_drafts_nav_item_counts_waiting_drafts(signed_in: Client) -> None:
    make_draft()
    make_manual_draft()
    make_draft().draft.reject()
    for status in ["processing", "failed", "posted"]:
        QuickAdd.objects.create(text="text", status=status)

    body = page(signed_in, "transaction_list")

    assert reverse("draft_list") in body
    assert 'aria-label="2 Drafts waiting"' in body


@pytest.mark.parametrize("name", ["draft_list", "quick_add_create"])
def test_pages_need_sign_in(client: Client, name: str) -> None:
    response = client.get(reverse(name))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


def test_without_an_api_key_quick_add_is_hidden_but_drafts_stay(
    signed_in: Client, settings: Settings
) -> None:
    settings.OPENROUTER_API_KEY = ""

    body = page(signed_in, "transaction_list")

    assert reverse("quick_add_create") not in body
    assert reverse("draft_list") in body
    assert "All-time cost" not in page(signed_in, "draft_list")
    response = signed_in.post(reverse("quick_add_create"), {"text": "lunch 850"})
    assert response.status_code == 404
    assert not QuickAdd.objects.exists()


def test_the_api_key_never_reaches_the_browser(signed_in: Client) -> None:
    make_quick_add()

    for name in ["transaction_list", "draft_list"]:
        assert "test-key" not in page(signed_in, name)
