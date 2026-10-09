from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.quick_add.models import QuickAdd

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def failed(text: str = "lunch at Toit 850") -> QuickAdd:
    return QuickAdd.objects.create(
        text=text,
        status=QuickAdd.Status.FAILED,
        failure_reason="Couldn't reach OpenRouter; try again later.",
    )


def test_the_drafts_page_offers_the_actions_only_on_failed_quick_adds(
    signed_in: Client,
) -> None:
    quick_add = failed("lunch 850")
    waiting = QuickAdd.objects.create(text="taxi 300")

    body = signed_in.get(reverse("draft_list")).content.decode()

    for action in ("quick_add_retry", "quick_add_resubmit", "quick_add_discard"):
        assert reverse(action, args=[quick_add.pk]) in body
        assert reverse(action, args=[waiting.pk]) not in body
    assert 'name="text" value="lunch 850"' in body


def test_retry_queues_a_failed_quick_add_again(signed_in: Client) -> None:
    quick_add = failed()

    response = signed_in.post(reverse("quick_add_retry", args=[quick_add.pk]))

    assert response["Location"] == reverse("draft_list")
    quick_add.refresh_from_db()
    assert (quick_add.status, quick_add.failure_reason) == (
        QuickAdd.Status.PROCESSING,
        "",
    )
    assert ProcrastinateJob.objects.get().args == {"quick_add_id": quick_add.pk}


@pytest.mark.parametrize("action", ["quick_add_retry", "quick_add_discard"])
@pytest.mark.parametrize(
    "status",
    [QuickAdd.Status.PROCESSING, QuickAdd.Status.DRAFT, QuickAdd.Status.POSTED],
)
def test_actions_are_only_for_failed_quick_adds(
    signed_in: Client, action: str, status: QuickAdd.Status
) -> None:
    quick_add = QuickAdd.objects.create(text="lunch at Toit 850", status=status)

    response = signed_in.post(reverse(action, args=[quick_add.pk]))

    assert response.status_code == 404
    quick_add.refresh_from_db()
    assert quick_add.status == status
    assert not ProcrastinateJob.objects.exists()


def test_discard_hides_a_failed_quick_add_but_keeps_it(signed_in: Client) -> None:
    quick_add = failed("lunch at Toit 850")

    response = signed_in.post(
        reverse("quick_add_discard", args=[quick_add.pk]), follow=True
    )

    assert response.redirect_chain == [(reverse("draft_list"), 302)]
    assert "lunch at Toit 850" not in response.content.decode()
    quick_add.refresh_from_db()
    assert quick_add.status == QuickAdd.Status.REJECTED
    assert not ProcrastinateJob.objects.exists()


def test_resubmit_saves_the_edited_text_and_queues_it(signed_in: Client) -> None:
    quick_add = failed("lunch 850")

    response = signed_in.post(
        reverse("quick_add_resubmit", args=[quick_add.pk]),
        {"text": "lunch at Toit 850 on hdfc card"},
    )

    assert response["Location"] == reverse("draft_list")
    quick_add.refresh_from_db()
    assert (quick_add.text, quick_add.status, quick_add.failure_reason) == (
        "lunch at Toit 850 on hdfc card",
        QuickAdd.Status.PROCESSING,
        "",
    )
    assert ProcrastinateJob.objects.get().args == {"quick_add_id": quick_add.pk}


@pytest.mark.parametrize(
    ("text", "message"),
    [("  ", "Write what happened"), ("x" * 501, "at most 500 characters")],
)
def test_resubmit_rejects_empty_or_over_long_text(
    signed_in: Client, text: str, message: str
) -> None:
    quick_add = failed("lunch 850")

    response = signed_in.post(
        reverse("quick_add_resubmit", args=[quick_add.pk]), {"text": text}, follow=True
    )

    assert response.redirect_chain == [(reverse("draft_list"), 302)]
    assert message in response.content.decode()
    quick_add.refresh_from_db()
    assert (quick_add.text, quick_add.status) == ("lunch 850", QuickAdd.Status.FAILED)
    assert not ProcrastinateJob.objects.exists()


def test_resubmit_is_only_for_failed_quick_adds(signed_in: Client) -> None:
    quick_add = QuickAdd.objects.create(text="lunch 850", status=QuickAdd.Status.DRAFT)

    response = signed_in.post(
        reverse("quick_add_resubmit", args=[quick_add.pk]),
        {"text": "lunch at Toit 850"},
    )

    assert response.status_code == 404
    quick_add.refresh_from_db()
    assert quick_add.text == "lunch 850"
