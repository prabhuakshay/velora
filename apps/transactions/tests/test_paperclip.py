from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import DjangoAssertNumQueries

pytestmark = pytest.mark.django_db


def record_with_attachments(description: str, attachments: int) -> Transaction:
    transaction = Transaction.objects.create(
        date=date(2026, 3, 1), description=description
    )
    transaction.splits.create(
        from_account=make_account(f"{description} bank", "asset"),
        to_account=make_account(f"{description} shop", "expense"),
        amount=Decimal("100.00"),
    )
    for i in range(attachments):
        transaction.attachments.create(
            file=ContentFile(b"receipt", name="receipt.pdf"),
            original_name=f"receipt-{i}.pdf",
            content_type="application/pdf",
            size=7,
        )
    return transaction


def list_page(client: Client) -> str:
    return client.get(reverse("transaction_list")).content.decode()


def test_transaction_with_attachments_shows_paperclip_and_count(
    signed_in: Client,
) -> None:
    record_with_attachments("Fridge", 2)

    body = list_page(signed_in)

    assert 'aria-label="2 Attachments"' in body


def test_one_attachment_is_counted_in_the_singular(signed_in: Client) -> None:
    record_with_attachments("Fridge", 1)

    assert 'aria-label="1 Attachment"' in list_page(signed_in)


def test_transaction_without_attachments_shows_no_paperclip(
    signed_in: Client,
) -> None:
    record_with_attachments("Coffee", 0)

    assert "Attachment" not in list_page(signed_in)


def test_attachments_do_not_inflate_the_total(signed_in: Client) -> None:
    record_with_attachments("Fridge", 3)

    body = list_page(signed_in)

    assert "100.00" in body
    assert "300.00" not in body


@pytest.mark.parametrize("transactions", [1, 4])
def test_list_query_count_does_not_grow_with_attachments(
    signed_in: Client,
    django_assert_num_queries: DjangoAssertNumQueries,
    transactions: int,
) -> None:
    for i in range(transactions):
        record_with_attachments(f"Item {i}", 2)

    with django_assert_num_queries(7):
        signed_in.get(reverse("transaction_list"))
