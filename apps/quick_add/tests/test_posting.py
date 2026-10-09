from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse

from apps.accounts.merge import AccountMerge
from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft, QuickAdd
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def make_draft(
    *splits: tuple[Account, Account, str],
    text: str = "lunch at Toit 850",
    **fields: Any,
) -> QuickAdd:
    note = QuickAdd.objects.create(text=text, status=QuickAdd.Status.DRAFT)
    draft = Draft.objects.create(quick_add=note, date=date(2026, 10, 8), **fields)
    for source, destination, amount in splits:
        draft.splits.create(
            from_account=source, to_account=destination, amount=Decimal(amount)
        )
    return note


def post(client: Client, note: QuickAdd) -> str:
    response = client.post(reverse("draft_post", args=[note.pk]), follow=True)
    assert response.redirect_chain == [(reverse("draft_list"), 302)]
    return response.content.decode()


def test_posting_creates_the_transaction_and_links_it(signed_in: Client) -> None:
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

    post(signed_in, note)

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
    note.refresh_from_db()
    assert note.status == QuickAdd.Status.POSTED
    assert note.posted_without_edits
    assert note.transaction == transaction


def test_posting_creates_the_new_party(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "1200"), new_party_name="Brik Oven")

    post(signed_in, note)

    assert Transaction.objects.get().party == Party.objects.get(name="Brik Oven")


def test_posting_reuses_a_party_matching_the_new_name_in_any_case(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    note = make_draft((card, food, "850"), new_party_name="toit brewpub")

    post(signed_in, note)

    assert Transaction.objects.get().party == toit
    assert Party.objects.count() == 1


def test_posting_fails_with_a_reason_once_an_account_is_deactivated(
    signed_in: Client,
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "1200"), new_party_name="Brik Oven")
    card.hidden = True
    card.save()

    body = post(signed_in, note)

    assert "Couldn't post" in body
    assert "That Account is inactive or no longer exists." in body
    assert f"{reverse('transaction_create')}?quick_add={note.pk}" in body
    assert not Transaction.objects.exists()
    assert not Party.objects.exists()
    note.refresh_from_db()
    assert note.status == QuickAdd.Status.DRAFT


def test_posting_fails_once_an_account_is_merged_away(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    fun = make_account("Fun", "expense")
    note = make_draft((card, food, "850"), (card, fun, "150"))
    AccountMerge(source=fun, target=food).run()

    body = post(signed_in, note)

    assert "Couldn't post: Split 2 To: This field is required." in body
    assert "Removed Account" in body
    assert not Transaction.objects.exists()


def test_rejecting_keeps_the_draft_and_creates_no_party(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "1200"), new_party_name="Brik Oven")

    response = signed_in.post(reverse("draft_reject", args=[note.pk]))

    assert response["Location"] == reverse("draft_list")
    note.refresh_from_db()
    assert note.status == QuickAdd.Status.REJECTED
    assert note.draft.splits.count() == 1
    assert not Party.objects.exists()
    assert not Transaction.objects.exists()


def test_a_draft_offers_post_and_reject(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))

    body = signed_in.get(reverse("draft_list")).content.decode()

    assert reverse("draft_post", args=[note.pk]) in body
    assert reverse("draft_reject", args=[note.pk]) in body


@pytest.mark.parametrize("action", ["draft_post", "draft_reject"])
def test_posted_and_rejected_drafts_leave_the_drafts_page_and_badge(
    signed_in: Client, action: str
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"), text="lunch at Toit 850")

    signed_in.post(reverse(action, args=[note.pk]))

    body = signed_in.get(reverse("draft_list")).content.decode()
    assert "lunch at Toit 850" not in body
    assert "Drafts waiting" not in body


@pytest.mark.parametrize("action", ["draft_post", "draft_reject"])
def test_only_a_waiting_draft_can_be_posted_or_rejected(
    signed_in: Client, action: str
) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))
    signed_in.post(reverse("draft_post", args=[note.pk]))

    response = signed_in.post(reverse(action, args=[note.pk]))

    assert response.status_code == 404
    assert Transaction.objects.count() == 1


def test_balances_change_only_once_a_draft_is_posted(signed_in: Client) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    note = make_draft((card, food, "850"))

    def balance() -> Decimal:
        return Account.objects.with_balance().get(pk=card.pk).balance

    assert balance() == 0
    post(signed_in, note)
    assert balance() == Decimal(850)
