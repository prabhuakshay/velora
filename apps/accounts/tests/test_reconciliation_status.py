from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_reconciliation import bank_with_spending, reconcile
from apps.transactions.models import Split
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_back_dated_transaction_makes_a_reconciliation_show_as_off(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    fruit = make_account("Fruit", "expense")

    response = signed_in.post(
        reverse("transaction_create"), form_data(bank, fruit, "40")
    )

    assert response.status_code == 302
    page = page_text(view_page(signed_in, bank))
    assert "Reconciliation on 3 Mar 2026 is off by ₹40.00" in page
    assert "Reconciled through" not in page


def test_reconciled_through_falls_back_to_the_latest_that_still_matches(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    fruit = make_account("Fruit", "expense")
    record(date(2026, 3, 4), bank, fruit, "40", "Apples")

    page = page_text(view_page(signed_in, bank))

    assert "Reconciliation on 5 Mar 2026 is off by ₹40.00" in page
    assert "Reconciled through 3 Mar 2026" in page


def test_undoing_the_change_makes_it_match_again(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    fruit = make_account("Fruit", "expense")
    apples = record(date(2026, 3, 2), bank, fruit, "40", "Apples")
    apples.delete()

    page = page_text(view_page(signed_in, bank))

    assert "off by" not in page
    assert "Reconciled through 3 Mar 2026" in page


def test_editing_an_amount_on_a_reconciled_day_makes_it_off(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    split = Split.objects.get(transaction__description="Snacks")
    split.amount = Decimal(300)
    split.save()

    page = page_text(view_page(signed_in, bank))

    assert "Reconciliation on 5 Mar 2026 is off by ₹50.00" in page


def test_a_later_transaction_leaves_the_reconciliation_matching(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")

    page = page_text(view_page(signed_in, bank))

    assert "off by" not in page
    assert "Reconciled through 3 Mar 2026" in page


def test_liability_difference_reads_as_owed(signed_in: Client) -> None:
    card = opening("Card", "liability", "3000")
    rent = make_account("Rent", "expense")
    reconcile(signed_in, card, date(2026, 3, 3), "3000")
    record(date(2026, 3, 2), card, rent, "500", "Rent")

    page = page_text(view_page(signed_in, card))

    assert "Reconciliation on 3 Mar 2026 is off by -₹500.00" in page


def test_transactions_up_to_reconciled_through_are_marked_reconciled(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")

    page = page_text(view_page(signed_in, bank))

    assert "Weekly shop Reconciled" in page
    assert "Snacks Reconciled" not in page


def test_nothing_is_marked_reconciled_when_no_reconciliation_matches(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    fruit = make_account("Fruit", "expense")
    record(date(2026, 3, 2), bank, fruit, "40", "Apples")

    page = page_text(view_page(signed_in, bank))

    assert "Weekly shop Reconciled" not in page


def _queries_to_view(client: Client, account: Account) -> int:
    with CaptureQueriesContext(connection) as queries:
        view_page(client, account)
    return len(queries)


def test_page_query_count_does_not_grow_with_reconciliations(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    record(date(2026, 3, 4), bank, make_account("Fruit", "expense"), "1", "Apple")
    few = _queries_to_view(signed_in, bank)

    for day in range(6, 12):
        reconcile(signed_in, bank, date(2026, 3, day), "8249")

    assert _queries_to_view(signed_in, bank) == few


def test_reconciled_through_reaches_past_the_latest_five(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    for day in range(6, 12):
        reconcile(signed_in, bank, date(2026, 3, day), "8250")
    record(date(2026, 3, 4), bank, make_account("Fruit", "expense"), "40", "Apples")

    page = page_text(view_page(signed_in, bank))

    assert "Reconciliation on 11 Mar 2026 is off by ₹40.00" in page
    assert "Reconciled through 3 Mar 2026" in page
    assert "Show all 7" in page
