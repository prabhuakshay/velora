import json
import urllib.request
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from typing import TYPE_CHECKING, Any

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import AICall, Draft, QuickAdd
from apps.quick_add.tests.conftest import make_quick_add, process, reply, split

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
    quick_add = make_quick_add()
    fake_openrouter.replies += [
        reply(split(bank, food, "850"), mood="hungry"),
        reply(split(bank, food, "850")),
    ]

    process(quick_add)

    first, second = fake_openrouter.requests
    assert "mood" in second[-1]["content"]
    assert len(second) > len(first)
    assert QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.DRAFT
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
        "A Split cannot go from an Account to itself",
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
    quick_add = make_quick_add()
    broken = make_reply(bank, food)
    fake_openrouter.replies += [broken, broken]

    process(quick_add)

    assert len(fake_openrouter.requests) == 2
    failed = QuickAdd.objects.get(pk=quick_add.pk)
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
    quick_add = make_quick_add()
    fake_openrouter.replies.append(
        reply(
            *[split(bank, food, "10000000.00")] * 10,
            date=days_ago(365),
            new_party_name="x" * 100,
            description="x" * 200,
        )
    )

    process(quick_add)

    assert QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.DRAFT


def test_a_draft_made_after_a_failure_drops_the_old_reason(
    fake_openrouter: FakeOpenRouter, signed_in: Client, bank: Account, food: Account
) -> None:
    quick_add = make_quick_add()
    quick_add.failure_reason = "The AI's reply was invalid: Unknown field."
    quick_add.save()
    fake_openrouter.replies.append(reply(split(bank, food, "850")))

    process(quick_add)

    assert QuickAdd.objects.get(pk=quick_add.pk).failure_reason == ""
    assert "Unknown field" not in drafts_page(signed_in)


def openrouter_responds(monkeypatch: pytest.MonkeyPatch, body: object) -> None:
    """Make every request to OpenRouter get this JSON body back."""

    def urlopen(*_args: object, **_kwargs: object) -> BytesIO:
        return BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


USAGE = {"prompt_tokens": 10, "completion_tokens": 0, "cost": 0.0001}


@pytest.mark.parametrize(
    "body",
    [
        {"usage": USAGE},
        {"choices": [], "usage": USAGE},
        {"choices": [{"message": {"content": None}}], "usage": USAGE},
        {"choices": [{"message": None}], "usage": USAGE},
        ["not", "an", "object"],
    ],
    ids=["no choices", "empty choices", "null content", "null message", "list"],
)
def test_a_response_without_reply_content_fails_the_quick_add(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    openrouter_responds(monkeypatch, body)
    quick_add = make_quick_add()

    process(quick_add)

    failed = QuickAdd.objects.get(pk=quick_add.pk)
    assert failed.status == QuickAdd.Status.FAILED
    assert failed.failure_reason.startswith("The AI's reply was invalid")
    assert AICall.objects.count() == 2


def test_an_unexpected_error_fails_the_quick_add_instead_of_leaving_it_processing(
    fake_openrouter: FakeOpenRouter, signed_in: Client
) -> None:
    quick_add = make_quick_add()
    fake_openrouter.replies.append(RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        process(quick_add)

    failed = QuickAdd.objects.get(pk=quick_add.pk)
    assert failed.status == QuickAdd.Status.FAILED
    assert "Something went wrong" in drafts_page(signed_in)


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens": 10, "completion_tokens": 5, "cost": None}, (10, 5, 0)),
        ({"prompt_tokens": 10, "completion_tokens": 5, "cost": "free"}, (10, 5, 0)),
        (
            {"prompt_tokens": 10, "completion_tokens": 5, "cost": float("nan")},
            (10, 5, 0),
        ),
        ({"prompt_tokens": None, "completion_tokens": None, "cost": 0.5}, (0, 0, 0.5)),
        ({"prompt_tokens": -1, "completion_tokens": 5.0, "cost": 0}, (0, 5, 0)),
        (
            {"prompt_tokens": True, "completion_tokens": float("inf"), "cost": 0},
            (0, 0, 0),
        ),
        ({"prompt_tokens": "x", "completion_tokens": [], "cost": {}}, (0, 0, 0)),
        (None, (0, 0, 0)),
        ("usage", (0, 0, 0)),
        ({}, (0, 0, 0)),
    ],
    ids=[
        "null cost",
        "non-numeric cost",
        "NaN cost",
        "null tokens",
        "negative and float tokens",
        "bool and infinite tokens",
        "non-numeric everything",
        "null usage",
        "non-object usage",
        "empty usage",
    ],
)
def test_a_reply_with_unusable_usage_still_becomes_a_draft(
    monkeypatch: pytest.MonkeyPatch,
    bank: Account,
    food: Account,
    usage: object,
    expected: tuple[int, int, float],
) -> None:
    content = json.dumps(reply(split(bank, food, "850")))
    openrouter_responds(
        monkeypatch, {"choices": [{"message": {"content": content}}], "usage": usage}
    )
    quick_add = make_quick_add()

    process(quick_add)

    assert QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.DRAFT
    [call] = AICall.objects.all()
    assert (call.prompt_tokens, call.completion_tokens, call.cost) == pytest.approx(
        expected
    )
    assert call.succeeded


def test_a_reply_without_usage_still_becomes_a_draft(
    monkeypatch: pytest.MonkeyPatch, bank: Account, food: Account
) -> None:
    content = json.dumps(reply(split(bank, food, "850")))
    openrouter_responds(monkeypatch, {"choices": [{"message": {"content": content}}]})
    quick_add = make_quick_add()

    process(quick_add)

    assert QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.DRAFT
    [call] = AICall.objects.all()
    assert (call.prompt_tokens, call.completion_tokens, call.cost) == (0, 0, Decimal(0))
