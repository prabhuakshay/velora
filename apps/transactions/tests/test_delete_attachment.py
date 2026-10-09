from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.transactions.tests.conftest import stored_names, transaction_url
from apps.transactions.tests.test_edit_attachments import attach, recorded

if TYPE_CHECKING:
    from django.test import Client

    from apps.transactions.models import Attachment

pytestmark = pytest.mark.django_db


def delete_url(attachment: Attachment) -> str:
    return reverse("attachment_delete", kwargs={"pk": attachment.pk})


def test_deleting_removes_the_attachment_and_its_file(signed_in: Client) -> None:
    transaction = recorded()
    gone = attach(transaction, "wrong.pdf", b"%PDF wrong", "application/pdf")
    kept = attach(transaction, "bill.pdf", b"%PDF bill", "application/pdf")

    response = signed_in.post(delete_url(gone))

    assert response["Location"] == transaction_url("transaction_edit", transaction)
    assert list(transaction.attachments.all()) == [kept]
    assert stored_names() == [kept.file.name]


@pytest.mark.usefixtures("delete_fails")
def test_storage_failure_keeps_the_attachment_and_says_so(signed_in: Client) -> None:
    transaction = recorded()
    attachment = attach(transaction, "bill.pdf", b"%PDF bill", "application/pdf")

    response = signed_in.post(delete_url(attachment), follow=True)

    assert response.redirect_chain == [
        (transaction_url("transaction_edit", transaction), 302)
    ]
    assert (
        "Couldn&#x27;t remove attachments from storage; nothing was deleted. "
        "Try again." in response.content.decode()
    )
    assert list(transaction.attachments.all()) == [attachment]
    assert stored_names() == [attachment.file.name]


def test_a_file_already_gone_from_storage_still_lets_it_be_deleted(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attachment = attach(transaction, "bill.pdf", b"%PDF bill", "application/pdf")
    attachment.file.delete(save=False)

    response = signed_in.post(delete_url(attachment))

    assert response.status_code == 302
    assert not transaction.attachments.exists()


def test_get_is_refused(signed_in: Client) -> None:
    attachment = attach(recorded(), "bill.pdf", b"%PDF bill", "application/pdf")

    response = signed_in.get(delete_url(attachment))

    assert response.status_code == 405
    assert stored_names() == [attachment.file.name]


def test_signed_out_users_are_refused(client: Client) -> None:
    attachment = attach(recorded(), "bill.pdf", b"%PDF bill", "application/pdf")
    url = delete_url(attachment)

    response = client.post(url)

    assert response["Location"] == f"{reverse('login')}?next={url}"
    assert stored_names() == [attachment.file.name]


def test_edit_page_has_a_delete_button_for_each_attachment(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attachment = attach(transaction, "bill.pdf", b"%PDF bill", "application/pdf")

    body = signed_in.get(transaction_url("transaction_edit", transaction)).content

    assert f'action="{delete_url(attachment)}"' in body.decode()
