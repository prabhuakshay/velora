from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def recorded_rent() -> Transaction:
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    maintenance = make_account("Maintenance", "expense")
    transaction = Transaction.objects.create(
        date=date(2026, 9, 5),
        party=Party.objects.create(name="Landlord"),
        description="Flat rent",
    )
    transaction.splits.create(from_account=bank, to_account=rent, amount=Decimal(25000))
    transaction.splits.create(
        from_account=bank, to_account=maintenance, amount=Decimal(3000)
    )
    return transaction


def test_the_transaction_page_offers_to_make_a_schedule(signed_in: Client) -> None:
    transaction = recorded_rent()

    body = signed_in.get(
        reverse("transaction_edit", args=[transaction.pk])
    ).content.decode()

    assert f"{reverse('schedule_create')}?transaction={transaction.pk}" in body
    assert "Make a Schedule" in body


def test_a_schedule_made_from_a_transaction_is_prefilled(signed_in: Client) -> None:
    transaction = recorded_rent()

    body = signed_in.get(
        reverse("schedule_create"), {"transaction": transaction.pk}
    ).content.decode()

    assert ">\nFlat rent</textarea>" in body
    assert 'name="start_date" value="2026-10-05"' in body
    for name in ("Landlord", "Rent", "Maintenance"):
        assert f" selected>{name}</option>" in body
    assert body.count(" selected>Bank</option>") == 2
    assert 'name="splits-0-amount" value="25000.00"' in body
    assert 'name="splits-1-amount" value="3000.00"' in body
    assert 'name="splits-TOTAL_FORMS" value="2"' in body
