from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from urllib.error import HTTPError, URLError

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.quick_add.drafting import TransientError
from apps.quick_add.models import AICall, QuickAdd
from apps.quick_add.tasks import process_quick_add
from apps.quick_add.tests.conftest import make_quick_add, process, reply, split

if TYPE_CHECKING:
    from django.test import Client
    from procrastinate.jobs import Job

    from apps.quick_add.tests.conftest import FakeOpenRouter

pytestmark = pytest.mark.django_db


def drafts_page(client: Client) -> str:
    return client.get(reverse("draft_list")).content.decode()


def http_error(code: int) -> HTTPError:
    return HTTPError("https://openrouter.ai", code, "error", Message(), BytesIO())


@pytest.mark.parametrize(
    "error", [URLError("connection refused"), http_error(502), TimeoutError()]
)
def test_network_and_server_errors_are_retried_three_times(
    fake_openrouter: FakeOpenRouter,
    signed_in: Client,
    error: Exception,
) -> None:
    quick_add = make_quick_add()
    fake_openrouter.replies += [error] * 4

    for attempts in range(3):
        with pytest.raises(TransientError):
            process(quick_add, attempts=attempts)
        assert (
            QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.PROCESSING
        )
    process(quick_add, attempts=3)

    failed = QuickAdd.objects.get(pk=quick_add.pk)
    assert failed.status == QuickAdd.Status.FAILED
    assert "Couldn&#x27;t reach OpenRouter" in drafts_page(signed_in)
    calls = AICall.objects.all()
    assert [(call.model, call.succeeded) for call in calls] == [
        ("test/model", False)
    ] * 4


def test_retries_back_off() -> None:
    strategy = process_quick_add.retry_strategy
    assert strategy is not None
    now = datetime.now(tz=UTC)

    decisions = [
        strategy.get_retry_decision(
            exception=TransientError(),
            job=cast("Job", SimpleNamespace(attempts=attempts)),
        )
        for attempts in range(4)
    ]

    retry_at = [d.retry_at for d in decisions[:3] if d and d.retry_at]
    assert len(retry_at) == 3
    assert now < retry_at[0] < retry_at[1] < retry_at[2]
    assert decisions[3] is None


def test_a_server_error_then_a_valid_reply_becomes_a_draft(
    fake_openrouter: FakeOpenRouter,
) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Eating Out", "expense")
    quick_add = make_quick_add()
    fake_openrouter.replies += [http_error(503), reply(split(bank, food, "850"))]

    with pytest.raises(TransientError):
        process(quick_add)
    process(quick_add, attempts=1)

    assert QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.DRAFT
    assert list(AICall.objects.values_list("succeeded", flat=True)) == [False, True]


def test_a_server_error_on_the_corrective_retry_uses_up_the_one_retry(
    fake_openrouter: FakeOpenRouter, signed_in: Client
) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Eating Out", "expense")
    quick_add = make_quick_add()
    fake_openrouter.replies += [
        reply(split(bank, food, "850"), mood="hungry"),
        http_error(503),
    ]

    process(quick_add)

    assert len(fake_openrouter.requests) == 2
    failed = QuickAdd.objects.get(pk=quick_add.pk)
    assert failed.status == QuickAdd.Status.FAILED
    assert "mood" in failed.failure_reason


def test_a_refused_request_fails_without_retrying(
    fake_openrouter: FakeOpenRouter, signed_in: Client
) -> None:
    quick_add = make_quick_add()
    fake_openrouter.replies.append(http_error(401))

    process(quick_add)

    assert QuickAdd.objects.get(pk=quick_add.pk).status == QuickAdd.Status.FAILED
    assert "OpenRouter refused the request (HTTP 401)" in drafts_page(signed_in)
