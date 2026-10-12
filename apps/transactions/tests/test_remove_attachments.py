from typing import TYPE_CHECKING, Any

import pytest
from django.urls import NoReverseMatch, reverse

from apps.transactions.tests.conftest import (
    attach,
    form_data,
    queued_deletes,
    recorded,
    run_queued_deletes,
    stored_names,
    transaction_url,
    upload,
)

if TYPE_CHECKING:
    from django.test import Client
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

    from apps.transactions.models import Attachment, Transaction

pytestmark = pytest.mark.django_db


def edit(
    client: Client, transaction: Transaction, url: str | None = None, **fields: Any
) -> Response:
    split = transaction.splits.get()
    return client.post(
        url or transaction_url("transaction_edit", transaction),
        form_data(split.from_account, split.to_account, split_id=split.pk, **fields),
    )


def checkbox(attachment: Attachment) -> str:
    return f'name="remove_attachments" value="{attachment.pk}"'


def test_save_removes_the_ticked_attachments_with_the_other_edits(
    signed_in: Client,
) -> None:
    transaction = recorded()
    gone = attach(transaction, "wrong.pdf")
    kept = attach(transaction)
    url = f"{transaction_url('transaction_edit', transaction)}?next=/accounts/"

    response = edit(
        signed_in,
        transaction,
        url,
        description="Changed",
        remove_attachments=[gone.pk],
    )

    assert response["Location"] == "/accounts/"
    assert list(transaction.attachments.all()) == [kept]
    transaction.refresh_from_db()
    assert transaction.description == "Changed"
    run_queued_deletes()
    assert stored_names() == [kept.file.name]


@pytest.mark.usefixtures("delete_fails")
def test_storage_failure_doesnt_block_removing(signed_in: Client) -> None:
    transaction = recorded()
    attachment = attach(transaction)
    name = attachment.file.name

    response = edit(signed_in, transaction, remove_attachments=[attachment.pk])

    assert response.status_code == 302
    assert not transaction.attachments.exists()
    assert queued_deletes() == [name]


def test_failed_save_removes_nothing_and_keeps_the_box_ticked(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attachment = attach(transaction)

    response = edit(
        signed_in, transaction, amount="0", remove_attachments=[attachment.pk]
    )

    assert response.status_code == 200
    assert list(transaction.attachments.all()) == [attachment]
    assert f"{checkbox(attachment)} checked" in response.content.decode()


def test_another_transactions_attachment_cant_be_removed(signed_in: Client) -> None:
    transaction = recorded()
    other = attach(recorded("other"))

    response = edit(signed_in, transaction, remove_attachments=[other.pk])

    assert response.status_code == 200
    assert "Select a valid choice." in response.content.decode()
    assert other.transaction.attachments.get() == other


def test_at_the_limit_one_can_be_swapped_for_another_in_one_save(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attachments = [attach(transaction, f"page{n}.pdf") for n in range(10)]

    response = edit(
        signed_in,
        transaction,
        remove_attachments=[attachments[0].pk],
        attachments=upload("new.pdf", b"%PDF new"),
    )

    assert response.status_code == 302
    names = [a.original_name for a in transaction.attachments.all()]
    assert names == [*(f"page{n}.pdf" for n in range(1, 10)), "new.pdf"]


def test_at_the_limit_adding_without_removing_is_refused(signed_in: Client) -> None:
    transaction = recorded()
    for n in range(10):
        attach(transaction, f"page{n}.pdf")

    response = edit(signed_in, transaction, attachments=upload("new.pdf", b"%PDF new"))

    assert "at most 10 Attachments" in response.content.decode()
    assert transaction.attachments.count() == 10


def test_removed_sizes_dont_count_towards_the_total(signed_in: Client) -> None:
    transaction = recorded()
    big = attach(transaction, "big.pdf", b"%PDF" + b"0" * (9 * 1024 * 1024))

    response = edit(
        signed_in,
        transaction,
        remove_attachments=[big.pk],
        attachments=upload("new.pdf", b"%PDF" + b"0" * (2 * 1024 * 1024)),
    )

    assert response.status_code == 302
    assert [a.original_name for a in transaction.attachments.all()] == ["new.pdf"]


def test_edit_page_has_a_remove_toggle_for_each_attachment(
    signed_in: Client,
) -> None:
    transaction = recorded()
    attachment = attach(transaction, "receipt.pdf")

    body = signed_in.get(transaction_url("transaction_edit", transaction)).content

    page = body.decode()
    assert checkbox(attachment) in page
    assert 'aria-label="Remove receipt.pdf"' in page
    assert "delete-attachment-" not in page


def test_the_one_tap_delete_url_is_gone() -> None:
    with pytest.raises(NoReverseMatch):
        reverse("attachment_delete", kwargs={"pk": 1})
