from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from apps.quick_add import openrouter
from apps.quick_add.models import QuickAdd

if TYPE_CHECKING:
    from pytest_django import Settings


@pytest.fixture(autouse=True)
def _openrouter_key(settings: Settings) -> None:
    settings.OPENROUTER_API_KEY = "test-key"
    settings.OPENROUTER_MODEL = "test/model"


class FakeOpenRouter:
    """Stands in for openrouter.complete: hands out canned replies in order."""

    def __init__(self) -> None:
        self.replies: list[dict[str, Any]] = []
        self.requests: list[list[dict[str, str]]] = []

    def complete(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> openrouter.Reply:
        self.requests.append(messages)
        return openrouter.Reply(
            content=self.replies.pop(0),
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


def split(source: Any, destination: Any, amount: str) -> dict[str, Any]:
    return {
        "from_account_id": source.pk,
        "to_account_id": destination.pk,
        "amount": amount,
    }


def quick_add(text: str = "lunch at Toit 850 on hdfc card") -> QuickAdd:
    return QuickAdd.objects.create(text=text)
