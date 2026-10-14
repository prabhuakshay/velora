import re
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.transactions.tests.conftest import attach, recorded

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def record_many(count: int, start: int = 0) -> None:
    for i in range(start, start + count):
        transaction = recorded(f"Item {i}")
        if i % 5 == 0:
            attach(transaction)


def list_page(client: Client) -> str:
    return client.get(reverse("transaction_list")).content.decode()


def test_list_page_stays_small(signed_in: Client) -> None:
    record_many(25)

    body = list_page(signed_in)

    assert len(body.encode()) <= 85_000
    assert len(re.findall(r"<[a-zA-Z]", body)) <= 800
    assert body.count("data-transaction-detail=") == 1
    assert body.count("<dialog") <= 4


def test_list_page_size_grows_only_with_rows(signed_in: Client) -> None:
    record_many(5)
    five = len(list_page(signed_in).encode())
    record_many(20, start=5)

    twenty_five = len(list_page(signed_in).encode())

    assert twenty_five - five <= 25 * 1_500


def test_empty_list_has_no_detail(signed_in: Client) -> None:
    body = list_page(signed_in)

    assert "data-transaction-detail=" not in body
    assert "Nothing to show" in body
