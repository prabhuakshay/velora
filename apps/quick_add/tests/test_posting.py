from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.merge import AccountMerge
from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import QuickAdd
from apps.quick_add.tests.conftest import make_draft
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def post(client: Client, quick_add: QuickAdd) -> str:
    response = client.post(
        reverse("draft_post", args=[quick_add.draft.pk]), follow=True
    )
    assert response.redirect_chain == [(reverse("draft_list"), 302)]
    return response.content.decode()


def test_posting_creates_the_transaction_and_links_it(signed_in: Client) -> None:
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

    post(signed_in, quick_add)

    transaction = Transaction.objects.get()
    assert (transaction.date, transaction.party, transaction.description) == (
        date(2026, 10, 8),
        toit,
        "Team lunch",
    )
    assert [
        (split.from_account, split.to_account, split.amount)
        for split in transaction.splits.order_by("pk")
    ] == [(card, food, Decimal("850.00")), (card, fun, Decimal("150.50"))]
    quick_add.refresh_from_db()
    assert quick_add.status == QuickAdd.Status.POSTED
    assert quick_add.posted_without_edits
    assert quick_add.draft.transaction == transaction


def test_posting_creates_the_new_party(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "1200"), new_party_name="Brik Oven")

    post(signed_in, quick_add)

    assert Transaction.objects.get().party == Party.objects.get(name="Brik Oven")


def test_posting_reuses_a_party_matching_the_new_name_in_any_case(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    quick_add = make_draft((card, food, "850"), new_party_name="toit brewpub")

    post(signed_in, quick_add)

    assert Transaction.objects.get().party == toit
    assert Party.objects.count() == 1


def test_posting_fails_with_a_reason_once_an_account_is_deactivated(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "1200"), new_party_name="Brik Oven")
    card.hidden = True
    card.save()

    body = post(signed_in, quick_add)

    assert "Couldn't post" in body
    assert "That Account is inactive or no longer exists." in body
    assert reverse("draft_edit", args=[quick_add.draft.pk]) in body
    assert not Transaction.objects.exists()
    assert not Party.objects.exists()
    quick_add.refresh_from_db()
    assert quick_add.status == QuickAdd.Status.DRAFT


def test_posting_fails_once_an_account_is_merged_away(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    fun = make_account("Fun", "expense")
    quick_add = make_draft((card, food, "850"), (card, fun, "150"))
    AccountMerge(source=fun, target=food).run()

    body = post(signed_in, quick_add)

    assert "Couldn't post: Split 2 To: This field is required." in body
    assert "Removed Account" in body
    assert not Transaction.objects.exists()


def test_merging_the_drafts_party_posts_it_with_the_target(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    source = Party.objects.create(name="Toit")
    target = Party.objects.create(name="Toit Brewpub")
    quick_add = make_draft((card, food, "850"), party=source)

    signed_in.post(reverse("party_merge", args=[source.pk]), {"target": target.pk})
    post(signed_in, quick_add)

    assert Transaction.objects.get().party == target


def test_a_party_on_a_draft_cannot_be_deleted(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit")
    quick_add = make_draft((card, food, "850"), party=toit)

    response = signed_in.post(reverse("party_delete", args=[toit.pk]), follow=True)

    assert response.redirect_chain == [(reverse("party_merge", args=[toit.pk]), 302)]
    assert "used by Transactions or Drafts" in response.content.decode()
    quick_add.draft.refresh_from_db()
    assert quick_add.draft.party == toit


def test_rejecting_keeps_the_draft_and_creates_no_party(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "1200"), new_party_name="Brik Oven")

    response = signed_in.post(reverse("draft_reject", args=[quick_add.draft.pk]))

    assert response["Location"] == reverse("draft_list")
    quick_add.refresh_from_db()
    assert quick_add.status == QuickAdd.Status.REJECTED
    assert quick_add.draft.splits.count() == 1
    assert not Party.objects.exists()
    assert not Transaction.objects.exists()


def test_a_draft_offers_post_and_reject(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert reverse("draft_post", args=[quick_add.draft.pk]) in body
    assert reverse("draft_reject", args=[quick_add.draft.pk]) in body


@pytest.mark.parametrize("action", ["draft_post", "draft_reject"])
def test_posted_and_rejected_drafts_leave_the_drafts_page_and_badge(
    signed_in: Client, action: str
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"), text="lunch at Toit 850")

    signed_in.post(reverse(action, args=[quick_add.draft.pk]))

    body = signed_in.get(reverse("draft_list")).content.decode()
    assert "lunch at Toit 850" not in body
    assert "Drafts waiting" not in body


@pytest.mark.parametrize("action", ["draft_post", "draft_reject"])
def test_only_a_waiting_draft_can_be_posted_or_rejected(
    signed_in: Client, action: str
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))
    signed_in.post(reverse("draft_post", args=[quick_add.draft.pk]))

    response = signed_in.post(reverse(action, args=[quick_add.draft.pk]))

    assert response.status_code == 404
    assert Transaction.objects.count() == 1


def test_balances_change_only_once_a_draft_is_posted(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    quick_add = make_draft((card, food, "850"))

    def balance() -> Decimal:
        return Account.objects.with_balance().get(pk=card.pk).balance

    assert balance() == 0
    post(signed_in, quick_add)
    assert balance() == Decimal(850)
