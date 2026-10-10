from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.quick_add.models import Draft, QuickAdd
from apps.quick_add.tests.conftest import make_draft
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

TEXT = "rent 25000 to landlord"
REASON = "the amount '25000' is not a number"


def failed_quick_add() -> QuickAdd:
    return QuickAdd.objects.create(
        text=TEXT, status=QuickAdd.Status.FAILED, failure_reason=REASON
    )


def drafts_page(client: Client) -> str:
    return client.get(reverse("draft_list")).content.decode()


def test_privacy_mode_hides_quick_add_text_and_failure_reason(
    signed_in: Client,
) -> None:
    failed_quick_add()
    make_draft((make_account("Bank", "asset"), None, None), text=TEXT)
    turn_on(signed_in)

    page = drafts_page(signed_in)

    assert "25000" not in page
    assert page.count("“Hidden in Privacy Mode”") == 2
    assert "Failed: Hidden in Privacy Mode" in page
    assert 'name="text" value="" placeholder="Hidden in Privacy Mode"' in page


def test_quick_add_text_and_failure_reason_show_while_off(signed_in: Client) -> None:
    failed_quick_add()
    make_draft((make_account("Bank", "asset"), None, None), text=TEXT)

    page = drafts_page(signed_in)

    assert page.count(TEXT) == 3
    assert "the amount &#x27;25000&#x27; is not a number" in page
    assert "Hidden in Privacy Mode" not in page


def test_draft_edit_sends_to_privacy_mode_off_page(signed_in: Client) -> None:
    quick_add = make_draft((make_account("Bank", "asset"), None, "850"))
    draft = Draft.objects.get(quick_add=quick_add)
    url = reverse("draft_edit", args=[draft.pk])
    turn_on(signed_in)

    get = signed_in.get(url)
    post = signed_in.post(url, {"description": "Changed"})

    for response in (get, post):
        assert response.status_code == 302
        assert response["Location"] == privacy_mode_off_url(url)
    draft.refresh_from_db()
    assert draft.description != "Changed"
