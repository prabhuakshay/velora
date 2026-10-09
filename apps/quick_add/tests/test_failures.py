from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import AICall, Draft, QuickAdd
from apps.quick_add.tests.conftest import process, quick_add, reply, split

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.test import Client

    from apps.quick_add.tests.conftest import FakeOpenRouter

pytestmark = pytest.mark.django_db

UNKNOWN = 10**9


@pytest.fixture
def bank() -> Account:
    return make_account("Bank", "asset")


@pytest.fixture
def food() -> Account:
    return make_account("Eating Out", "expense")


def drafts_page(client: Client) -> str:
    return client.get(reverse("draft_list")).content.decode()


def days_ago(days: int) -> str:
    return (timezone.localdate() - timedelta(days=days)).isoformat()


def opened(name: str, days: int) -> Account:
    account = make_account(name, "asset")
    account.opening_balance_date = timezone.localdate() - timedelta(days=days)
    account.save()
    return account


def test_an_invalid_reply_is_retried_once_with_the_errors_fed_back(
    fake_openrouter: FakeOpenRouter, signed_in: Client, bank: Account, food: Account
) -> None:
    note = quick_add()
    fake_openrouter.replies += [
        reply(split(bank, food, "850"), mood="hungry"),
        reply(split(bank, food, "850")),
    ]

    process(note)

    first, second = fake_openrouter.requests
    assert "mood" in second[-1]["content"]
    assert len(second) > len(first)
    assert QuickAdd.objects.get(pk=note.pk).status == QuickAdd.Status.DRAFT
    assert list(AICall.objects.values_list("succeeded", flat=True)) == [False, True]
    assert "Eating Out" in drafts_page(signed_in)


BROKEN_REPLIES: dict[str, tuple[Callable[[Account, Account], Any], str]] = {
    "unparsable date": (
        lambda bank, food: reply(split(bank, food, "850"), date="last tuesday"),
        "is not a YYYY-MM-DD date",
    ),
    "future date": (
        lambda bank, food: reply(split(bank, food, "850"), date=days_ago(-1)),
        "The date cannot be after today.",
    ),
    "date over a year back": (
        lambda bank, food: reply(split(bank, food, "850"), date=days_ago(367)),
        "more than 1 year before the Quick Add",
    ),
    "no splits": (lambda _bank, _food: reply(), "There must be 1 to 10 Splits."),
    "eleven splits": (
        lambda bank, food: reply(*[split(bank, food, "1")] * 11),
        "There must be 1 to 10 Splits.",
    ),
    "splits sharing no account": (
        lambda bank, food: reply(
            split(bank, food, "1"),
            split(
                make_account("Card", "liability"), make_account("Fuel", "expense"), "1"
            ),
        ),
        "Splits must share a From or a To Account.",
    ),
    "zero amount": (
        lambda bank, food: reply(split(bank, food, "0")),
        "the amount must be greater than zero",
    ),
    "negative amount": (
        lambda bank, food: reply(split(bank, food, "-5")),
        "the amount must be greater than zero",
    ),
    "amount above a crore": (
        lambda bank, food: reply(split(bank, food, "10000000.01")),
        "the amount cannot be above ₹1,00,00,000",
    ),
    "three decimals": (
        lambda bank, food: reply(split(bank, food, "850.125")),
        "the amount can have at most 2 decimals",
    ),
    "amount not a number": (
        lambda bank, food: reply(split(bank, food, "lots")),
        "is not a number",
    ),
    "unknown account": (
        lambda _bank, food: reply(
            {"from_account_id": UNKNOWN, "to_account_id": food.pk, "amount": "850"}
        ),
        f"Account {UNKNOWN} is unknown or inactive",
    ),
    "inactive account": (
        lambda _bank, food: reply(
            split(make_account("Old Wallet", "asset", hidden=True), food, "850")
        ),
        "is unknown or inactive",
    ),
    "same account": (
        lambda bank, _food: reply(split(bank, bank, "850")),
        "a Split cannot go from an Account to itself",
    ),
    "direction rule": (
        lambda bank, _food: reply(split(bank, make_account("Salary", "income"), "850")),
        "An Income Account can only be a source.",
    ),
    "date before an opening balance": (
        lambda _bank, food: reply(
            split(opened("New Bank", days=10), food, "850"), date=days_ago(20)
        ),
        "before the Opening Balance date of New Bank",
    ),
    "unknown party": (
        lambda bank, food: reply(split(bank, food, "850"), party_id=UNKNOWN),
        f"Party {UNKNOWN} is unknown.",
    ),
    "long new party name": (
        lambda bank, food: reply(split(bank, food, "850"), new_party_name="x" * 101),
        "The new Party name can be at most 100 characters.",
    ),
    "party and new party name": (
        lambda bank, food: reply(
            split(bank, food, "850"),
            party_id=Party.objects.create(name="Toit").pk,
            new_party_name="Toit Brewpub",
        ),
        "Give a Party ID or a new Party name, not both.",
    ),
    "long description": (
        lambda bank, food: reply(split(bank, food, "850"), description="x" * 201),
        "The description can be at most 200 characters.",
    ),
    "unknown field": (
        lambda bank, food: reply(split(bank, food, "850"), tags=["food"]),
        "Unknown field",
    ),
    "unknown split field": (
        lambda bank, food: reply(split(bank, food, "850") | {"tag": "food"}),
        "Unknown field",
    ),
    "missing field": (
        lambda bank, food: {"splits": [split(bank, food, "850")]},
        "Missing field",
    ),
    "malformed output": (
        lambda _bank, _food: "Sure! Here is your Transaction",
        "The reply must be a JSON object.",
    ),
}


@pytest.mark.parametrize("case", BROKEN_REPLIES)
def test_a_reply_breaking_a_rule_twice_fails_the_quick_add(
    fake_openrouter: FakeOpenRouter,
    signed_in: Client,
    bank: Account,
    food: Account,
    case: str,
) -> None:
    make_reply, reason = BROKEN_REPLIES[case]
    note = quick_add()
    broken = make_reply(bank, food)
    fake_openrouter.replies += [broken, broken]

    process(note)

    assert len(fake_openrouter.requests) == 2
    failed = QuickAdd.objects.get(pk=note.pk)
    assert failed.status == QuickAdd.Status.FAILED
    assert reason in failed.failure_reason
    assert not Draft.objects.exists()
    assert escape(reason) in drafts_page(signed_in)


def test_a_reply_at_every_limit_becomes_a_draft(
    fake_openrouter: FakeOpenRouter, bank: Account, food: Account
) -> None:
    Account.objects.filter(pk=bank.pk).update(
        opening_balance_date=timezone.localdate() - timedelta(days=365)
    )
    note = quick_add()
    fake_openrouter.replies.append(
        reply(
            *[split(bank, food, "10000000.00")] * 10,
            date=days_ago(365),
            new_party_name="x" * 100,
            description="x" * 200,
        )
    )

    process(note)

    assert QuickAdd.objects.get(pk=note.pk).status == QuickAdd.Status.DRAFT


def test_a_draft_made_after_a_failure_drops_the_old_reason(
    fake_openrouter: FakeOpenRouter, signed_in: Client, bank: Account, food: Account
) -> None:
    note = quick_add()
    note.failure_reason = "The AI's reply was invalid: Unknown field."
    note.save()
    fake_openrouter.replies.append(reply(split(bank, food, "850")))

    process(note)

    assert QuickAdd.objects.get(pk=note.pk).failure_reason == ""
    assert "Unknown field" not in drafts_page(signed_in)
