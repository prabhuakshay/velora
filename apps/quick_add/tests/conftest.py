from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from apps.quick_add import openrouter
from apps.quick_add.models import Draft, QuickAdd
from apps.quick_add.tasks import process_quick_add

if TYPE_CHECKING:
    from procrastinate import JobContext
    from pytest_django import Settings

    from apps.accounts.models import Account


@pytest.fixture(autouse=True)
def _openrouter_key(settings: Settings) -> None:
    settings.OPENROUTER_API_KEY = "test-key"
    settings.OPENROUTER_MODEL = "test/model"


class FakeOpenRouter:
    """Stands in for openrouter.complete: hands out canned replies in order.

    A reply that is an exception is raised instead, as a failed request would.
    """

    def __init__(self) -> None:
        self.replies: list[Any] = []
        self.requests: list[list[dict[str, str]]] = []

    def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> openrouter.Reply:
        self.requests.append(messages)
        content = self.replies.pop(0)
        if isinstance(content, Exception):
            raise content
        return openrouter.Reply(
            content=content,
            model="test/model-2026",
            usage=openrouter.Usage(
                prompt_tokens=1200, completion_tokens=80, cost=Decimal("0.00042")
            ),
        )


@pytest.fixture
def fake_openrouter(monkeypatch: pytest.MonkeyPatch) -> FakeOpenRouter:
    fake = FakeOpenRouter()
    monkeypatch.setattr(openrouter, "complete", fake.complete)
    return fake


def reply(*splits: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A valid AI reply with the given Splits; other fields default to null."""
    return {
        "date": None,
        "party_id": None,
        "new_party_name": None,
        "description": None,
        "splits": list(splits),
        **fields,
    }


def split(source: Any, destination: Any, amount: str | None) -> dict[str, Any]:
    return {
        "from_account_id": source.pk,
        "to_account_id": destination.pk,
        "amount": amount,
    }


def make_quick_add(text: str = "lunch at Toit 850 on hdfc card") -> QuickAdd:
    return QuickAdd.objects.create(text=text)


def make_draft(
    *splits: tuple[Account | None, Account | None, str | None],
    text: str = "lunch at Toit 850",
    **fields: Any,
) -> QuickAdd:
    quick_add = QuickAdd.objects.create(text=text, status=QuickAdd.Status.DRAFT)
    add_draft(splits, source=Draft.Source.QUICK_ADD, quick_add=quick_add, **fields)
    return quick_add


def make_manual_draft(
    *splits: tuple[Account | None, Account | None, str | None], **fields: Any
) -> Draft:
    return add_draft(splits, source=Draft.Source.MANUAL, **fields)


def add_draft(
    splits: tuple[tuple[Account | None, Account | None, str | None], ...],
    **fields: Any,
) -> Draft:
    """A waiting Draft dated 8 Oct 2026, with the given Splits; None leaves a gap."""
    draft = Draft.objects.create(**{"date": date(2026, 10, 8), **fields})
    for source, destination, amount in splits:
        draft.splits.create(
            from_account=source,
            to_account=destination,
            amount=None if amount is None else Decimal(amount),
        )
    return draft


def process(quick_add: QuickAdd, *, attempts: int = 0) -> None:
    """Run the job as the worker would on its `attempts`-th retry."""
    context = SimpleNamespace(job=SimpleNamespace(attempts=attempts))
    process_quick_add(cast("JobContext", context), quick_add_id=quick_add.pk)
