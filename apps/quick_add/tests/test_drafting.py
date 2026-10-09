from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone

from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import AICall, QuickAdd
from apps.quick_add.tests.conftest import process, quick_add, reply, split

if TYPE_CHECKING:
    from apps.quick_add.tests.conftest import FakeOpenRouter

pytestmark = pytest.mark.django_db


def test_a_valid_reply_becomes_a_draft(fake_openrouter: FakeOpenRouter) -> None:
    card = make_account("HDFC Card", "liability")
    food = make_account("Eating Out", "expense")
    toit = Party.objects.create(name="Toit Brewpub")
    lunch = quick_add()
    fake_openrouter.replies.append(
        reply(
            split(card, food, "850.00"),
            date="2026-10-08",
            party_id=toit.pk,
            description="Team lunch",
        )
    )

    process(lunch)

    lunch.refresh_from_db()
    assert lunch.status == QuickAdd.Status.DRAFT
    draft = lunch.draft
    assert (draft.date, draft.party, draft.new_party_name, draft.description) == (
        date(2026, 10, 8),
        toit,
        "",
        "Team lunch",
    )
    assert [(s.from_account, s.to_account, s.amount) for s in draft.splits.all()] == [
        (card, food, Decimal("850.00"))
    ]


def test_several_splits_become_draft_splits(fake_openrouter: FakeOpenRouter) -> None:
    card = make_account("HDFC Card", "liability")
    groceries = make_account("Groceries", "expense")
    household = make_account("Household", "expense")
    note = quick_add("groceries 500 and household 300 on hdfc")
    fake_openrouter.replies.append(
        reply(split(card, groceries, "500"), split(card, household, "300"))
    )

    process(note)

    splits = QuickAdd.objects.get(pk=note.pk).draft.splits.all()
    assert [(s.to_account, s.amount) for s in splits] == [
        (groceries, Decimal(500)),
        (household, Decimal(300)),
    ]


def test_date_defaults_to_the_day_it_was_written(
    fake_openrouter: FakeOpenRouter,
) -> None:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    note = quick_add("rent 25000")
    written = datetime(2026, 9, 30, 12, tzinfo=timezone.get_current_timezone())
    QuickAdd.objects.filter(pk=note.pk).update(created_at=written)
    fake_openrouter.replies.append(reply(split(bank, rent, "25000")))

    process(note)

    assert QuickAdd.objects.get(pk=note.pk).draft.date == date(2026, 9, 30)


def test_a_new_party_is_only_named_not_created(
    fake_openrouter: FakeOpenRouter,
) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Eating Out", "expense")
    note = quick_add("dinner at Brik Oven 1200")
    fake_openrouter.replies.append(
        reply(split(bank, food, "1200"), new_party_name="Brik Oven")
    )

    process(note)

    draft = QuickAdd.objects.get(pk=note.pk).draft
    assert (draft.party, draft.new_party_name) == (None, "Brik Oven")
    assert not Party.objects.exists()


def test_every_request_records_an_ai_call_with_its_usage(
    fake_openrouter: FakeOpenRouter,
) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Eating Out", "expense")
    note = quick_add()
    fake_openrouter.replies.append(reply(split(bank, food, "850")))

    process(note)

    call = AICall.objects.get()
    assert (
        call.quick_add,
        call.model,
        call.prompt_tokens,
        call.completion_tokens,
        call.cost,
        call.succeeded,
    ) == (note, "test/model-2026", 1200, 80, Decimal("0.00042"), True)


def test_the_prompt_has_the_text_and_only_active_accounts_and_parties(
    fake_openrouter: FakeOpenRouter,
) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Eating Out", "expense")
    make_account("Old Wallet", "asset", hidden=True)
    Party.objects.create(name="Toit Brewpub")
    Party.objects.create(name="Closed Cafe", hidden=True)
    note = quick_add()
    fake_openrouter.replies.append(reply(split(bank, food, "850")))

    process(note)

    [prompt] = fake_openrouter.requests
    sent = " ".join(message["content"] for message in prompt)
    for text in ["lunch at Toit 850 on hdfc card", "Bank", "Eating Out", "Toit"]:
        assert text in sent
    for text in ["Old Wallet", "Closed Cafe"]:
        assert text not in sent


def test_a_draft_changes_no_balance(fake_openrouter: FakeOpenRouter) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Eating Out", "expense")
    note = quick_add()
    fake_openrouter.replies.append(reply(split(bank, food, "850")))

    process(note)

    assert Account.objects.with_balance().get(pk=bank.pk).balance == 0
