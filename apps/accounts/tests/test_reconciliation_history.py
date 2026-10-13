from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.models import Reconciliation
from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_reconciliation import bank_with_spending, reconcile
from apps.users.models import NumberFormat

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_history_lists_reconciliations_newest_first(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    record(date(2026, 3, 4), bank, make_account("Fruit", "expense"), "40", "Apples")

    page = page_text(view_page(signed_in, bank))

    assert (
        "Reconciliations 5 Mar 2026 ₹8,250.00 Off by ₹40.00"
        " 3 Mar 2026 ₹8,500.00 Matches"
    ) in page


def delete_url(account: Account, when: date) -> str:
    reconciliation = account.reconciliations.get(date=when)
    return reverse(
        "reconciliation_delete",
        kwargs={
            "kind": account.kind,
            "pk": account.pk,
            "reconciliation_pk": reconciliation.pk,
        },
    )


def test_page_offers_to_delete_each_reconciliation(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")

    page = view_page(signed_in, bank)

    assert f'action="{delete_url(bank, date(2026, 3, 3))}"' in page


def test_deleting_removes_it_and_returns_to_the_page(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")

    response = signed_in.post(delete_url(bank, date(2026, 3, 3)))

    assert response.status_code == 302
    assert response["Location"] == account_url("account_transactions", bank)
    page = page_text(view_page(signed_in, bank))
    assert "Reconciliations" not in page
    assert "Reconciled through" not in page


def test_delete_needs_a_post(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")

    response = signed_in.get(delete_url(bank, date(2026, 3, 3)))

    assert response.status_code == 405
    assert "Reconciled through 3 Mar 2026" in page_text(view_page(signed_in, bank))


def test_delete_only_reaches_the_account_in_the_url(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    other = opening("Wallet", "asset", "0")
    url = delete_url(bank, date(2026, 3, 3)).replace(f"/{bank.pk}/", f"/{other.pk}/")

    assert signed_in.post(url).status_code == 404
    assert Reconciliation.objects.filter(account=bank).exists()


def test_deleting_the_latest_matching_falls_back_to_the_next_that_matches(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 1), "10000")
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    record(date(2026, 3, 2), bank, make_account("Fruit", "expense"), "40", "Apples")

    signed_in.post(delete_url(bank, date(2026, 3, 5)))

    page = page_text(view_page(signed_in, bank))
    assert "Reconciled through 1 Mar 2026" in page


def test_history_follows_number_format(signed_in: Client, user: User) -> None:
    user.number_format = NumberFormat.INTERNATIONAL
    user.save()
    bank = opening("Bank", "asset", "1500000")
    reconcile(signed_in, bank, date(2026, 3, 3), "1500000")

    page = page_text(view_page(signed_in, bank))

    assert "3 Mar 2026 ₹1,500,000.00 Matches" in page


def test_history_hides_amounts_in_privacy_mode(signed_in: Client, user: User) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    record(date(2026, 3, 4), bank, make_account("Fruit", "expense"), "40", "Apples")
    user.privacy_mode = True
    user.save()

    page = page_text(view_page(signed_in, bank))

    assert "5 Mar 2026 ₹•••• Off by ₹••••" in page
    assert "8,250" not in page
    assert "40.00" not in page


def test_history_shows_a_liability_in_credit_as_in_credit(signed_in: Client) -> None:
    card = opening("Card", "liability", "-500")
    reconcile(signed_in, card, date(2026, 3, 3), "-500")

    page = page_text(view_page(signed_in, card))

    assert "Reconciliations 3 Mar 2026 ₹500.00 in credit Matches" in page
