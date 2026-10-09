import re
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.quick_add.models import AICall, QuickAdd
from apps.quick_add.tests.conftest import quick_add

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def stats(client: Client) -> str:
    html = client.get(reverse("draft_list")).content.decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def call(note: QuickAdd, cost: str, *, months_ago: int = 0) -> None:
    made = AICall.objects.create(quick_add=note, model="test/model", cost=Decimal(cost))
    if months_ago:
        past = timezone.now().replace(day=1) - timedelta(days=31 * months_ago - 1)
        AICall.objects.filter(pk=made.pk).update(created_at=past)


def test_shows_all_time_and_this_months_cost_in_usd(signed_in: Client) -> None:
    note = quick_add()
    call(note, "0.0012")
    call(note, "0.00042")
    call(note, "0.25", months_ago=1)

    text = stats(signed_in)

    assert "All-time cost $0.2516" in text
    assert "This month $0.0016" in text


def test_shows_quick_adds_calls_and_average_cost_per_quick_add(
    signed_in: Client,
) -> None:
    first = quick_add()
    call(first, "0.001")
    call(first, "0.002")
    call(quick_add("taxi 300"), "0.003")
    quick_add("coffee 150")

    text = stats(signed_in)

    assert "Quick Adds 3" in text
    assert "AI calls 3" in text
    assert "Average per Quick Add $0.0020" in text


def test_with_no_quick_adds_the_average_is_zero(signed_in: Client) -> None:
    text = stats(signed_in)

    assert "Quick Adds 0" in text
    assert "Average per Quick Add $0.0000" in text


def posted(*, without_edits: bool) -> None:
    QuickAdd.objects.create(
        text="lunch 850",
        status=QuickAdd.Status.POSTED,
        posted_without_edits=without_edits,
    )


def test_shows_the_share_of_posted_drafts_posted_without_edits(
    signed_in: Client,
) -> None:
    posted(without_edits=True)
    posted(without_edits=True)
    posted(without_edits=False)
    QuickAdd.objects.create(text="taxi 300", status=QuickAdd.Status.REJECTED)

    assert "Posted without edits 67%" in stats(signed_in)


def test_with_nothing_posted_the_share_is_a_dash(signed_in: Client) -> None:
    quick_add()

    assert "Posted without edits —" in stats(signed_in)
