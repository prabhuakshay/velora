from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party, Tag
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import attach, recorded, transaction_url
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

HTMX = {"HX-Request": "true"}


def detail_url(transaction: Transaction, next_url: str = "") -> str:
    url = transaction_url("transaction_detail", transaction)
    return f"{url}?next={next_url}" if next_url else url


def test_detail_fragment_shows_one_transaction(signed_in: Client) -> None:
    shown = recorded("Toit")
    other = recorded("Other")
    came_from = reverse("transaction_list") + "?q=Toit"

    body = signed_in.get(detail_url(shown, came_from), headers=HTMX).content.decode()

    assert "<html" not in body
    assert body.count("data-transaction-detail=") == 1
    assert f'data-transaction-detail="{shown.pk}"' in body
    assert "Other" not in body
    assert f'id="delete-transaction-{shown.pk}"' in body
    assert f'id="delete-transaction-{other.pk}"' not in body
    delete_url = transaction_url("transaction_delete", shown)
    assert f'action="{delete_url}?next=/transactions/%3Fq%3DToit"' in body


def test_detail_fragment_announces_the_transaction(signed_in: Client) -> None:
    transaction = Transaction.objects.create(
        date=date(2026, 10, 3), party=Party.objects.create(name="Toit")
    )
    transaction.splits.create(
        from_account=make_account("Bank", "asset"),
        to_account=make_account("Food", "expense"),
        amount=Decimal("850.00"),
    )

    body = signed_in.get(detail_url(transaction), headers=HTMX).content.decode()

    assert 'data-title="Toit' in body
    assert 'data-amount="₹850.00"' in body
    assert 'data-date="3 Oct 2026"' in body


def test_detail_without_htmx_is_a_full_page(signed_in: Client) -> None:
    transaction = recorded("Toit")
    came_from = reverse("transaction_list") + "?q=Toit"

    body = signed_in.get(detail_url(transaction, came_from)).content.decode()

    assert "<html" in body
    assert f'data-transaction-detail="{transaction.pk}"' in body
    assert 'href="/transactions/?q=Toit"' in body
    delete_url = transaction_url("transaction_delete", transaction)
    assert f'href="{delete_url}?next=/transactions/%3Fq%3DToit"' in body


def test_detail_ignores_a_next_on_another_site(signed_in: Client) -> None:
    transaction = recorded("Toit")

    response = signed_in.get(detail_url(transaction, "https://evil.example/"))

    body = response.content.decode()
    assert 'href="https://evil.example/"' not in body
    assert f'href="{reverse("transaction_list")}"' in body


def test_detail_unknown_is_404(signed_in: Client) -> None:
    response = signed_in.get(reverse("transaction_detail", args=[999]))

    assert response.status_code == 404


def test_detail_needs_login(client: Client) -> None:
    url = reverse("transaction_detail", args=[1])

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_detail_fragment_masks_amounts_in_privacy_mode(signed_in: Client) -> None:
    transaction = recorded("Toit")
    turn_on(signed_in)

    body = signed_in.get(detail_url(transaction), headers=HTMX).content.decode()

    assert "100.00" not in body
    assert 'data-amount=""' in body


def queries_for(client: Client, transaction: Transaction) -> int:
    with CaptureQueriesContext(connection) as queries:
        client.get(detail_url(transaction), headers=HTMX)
    return len(queries)


def test_detail_query_count_does_not_grow(signed_in: Client) -> None:
    simple = recorded("Simple")
    busy = recorded("Busy")
    tags = [Tag.objects.create(name=f"Tag {i}") for i in range(3)]
    for i in range(2):
        busy.splits.create(
            from_account=make_account(f"From {i}", "asset"),
            to_account=make_account(f"To {i}", "expense"),
            amount=Decimal(1),
        )
    for split in busy.splits.all():
        split.tags.set(tags)
    for i in range(3):
        attach(busy, f"bill-{i}.pdf")

    assert queries_for(signed_in, busy) == queries_for(signed_in, simple)
