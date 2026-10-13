from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone

from apps.accounts.models import Reconciliation
from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.users.models import NumberFormat
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def reconcile(client: Client, account: Account, when: date, balance: str) -> str:
    """Post the Reconcile form, following the redirect back on success."""
    response = client.post(
        account_url("account_reconcile", account),
        {"date": when.isoformat(), "balance": balance},
        follow=True,
    )
    return response.content.decode()


def bank_with_spending() -> Account:
    """Opens with ₹10,000 on 1 Jan 2026; ₹1,500 out on 3 Mar and ₹250 on 5 Mar."""
    bank = opening("Bank", "asset", "10000")
    groceries = make_account("Groceries", "expense")
    record(date(2026, 3, 3), bank, groceries, "1500", "Weekly shop")
    record(date(2026, 3, 5), bank, groceries, "250", "Snacks")
    return bank


@pytest.mark.parametrize("kind", ["asset", "liability"])
def test_balance_accounts_offer_a_reconcile_form(signed_in: Client, kind: str) -> None:
    account = make_account("Bank", kind)

    page = view_page(signed_in, account)

    assert f'action="{account_url("account_reconcile", account)}"' in page


@pytest.mark.parametrize("kind", ["expense", "income"])
def test_income_and_expense_accounts_have_no_reconcile_form(
    signed_in: Client, kind: str
) -> None:
    account = make_account("Groceries", kind)

    page = view_page(signed_in, account)

    assert "Reconcile" not in page
    url = account_url("account_reconcile", account)
    assert (
        signed_in.post(url, {"date": "2026-03-03", "balance": "0"}).status_code == 404
    )


def test_reconcile_date_defaults_to_today(signed_in: Client) -> None:
    page = view_page(signed_in, make_account("Bank", "asset"))

    assert f'value="{timezone.localdate().isoformat()}"' in page


def test_matching_balance_counts_that_days_splits_and_is_recorded(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 3), "8500.00"))

    assert "Reconciled through 3 Mar 2026" in page
    assert Reconciliation.objects.get().balance == 8500


def test_page_shows_the_latest_reconciliation(signed_in: Client) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 3), "8500"))

    assert "Reconciled through 5 Mar 2026" in page
    assert "Reconciled through 3 Mar 2026" not in page


def test_reconciling_the_same_day_again_replaces_it(signed_in: Client) -> None:
    bank = bank_with_spending()
    fruit = make_account("Fruit", "expense")
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    record(date(2026, 3, 5), bank, fruit, "50", "Apples")

    reconcile(signed_in, bank, date(2026, 3, 5), "8200")

    assert list(Reconciliation.objects.values_list("date", "balance")) == [
        (date(2026, 3, 5), Decimal(8200))
    ]


def test_a_date_after_today_is_refused(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "0")
    tomorrow = timezone.localdate() + timedelta(days=1)

    page = page_text(reconcile(signed_in, bank, tomorrow, "0"))

    assert "Pick today or earlier." in page
    assert not Reconciliation.objects.exists()


def test_a_date_before_the_opening_balance_date_is_refused(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "0")

    page = page_text(reconcile(signed_in, bank, date(2025, 12, 31), "0"))

    assert "This Account opens on 1 Jan 2026; pick that or later." in page
    assert not Reconciliation.objects.exists()


def test_liability_balance_is_entered_as_what_is_owed(signed_in: Client) -> None:
    card = opening("Card", "liability", "3000")
    rent = make_account("Rent", "expense")
    record(date(2026, 3, 3), card, rent, "2000", "Rent")

    refused = page_text(reconcile(signed_in, card, date(2026, 3, 3), "-5000"))
    owed = page_text(reconcile(signed_in, card, date(2026, 3, 3), "5000"))

    assert "doesn&#x27;t match" in refused
    assert "Reconciled through 3 Mar 2026" in owed


def test_mismatch_saves_nothing_and_shows_the_difference(signed_in: Client) -> None:
    bank = bank_with_spending()

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 5), "8250.01"))

    assert "That doesn&#x27;t match Velora&#x27;s Balance on 5 Mar 2026." in page
    assert "Velora's Balance ₹8,250.00" in page
    assert "Off by ₹0.01" in page
    assert not Reconciliation.objects.exists()


def test_mismatch_lists_transactions_since_the_opening_balance_date(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 3), "8000"))

    assert "Since the Opening Balance on 1 Jan 2026" in page
    assert "Weekly shop" in page
    assert "Snacks" not in page


def test_mismatch_lists_transactions_since_the_previous_reconciliation(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 5), "8000"))

    assert "Since the Reconciliation on 3 Mar 2026" in page
    assert "Snacks to Groceries -₹250.00 ₹8,250.00" in page
    assert "Weekly shop" not in page


def test_mismatch_lists_transactions_since_the_last_reconciliation_still_matching(
    signed_in: Client,
) -> None:
    bank = bank_with_spending()
    reconcile(signed_in, bank, date(2026, 3, 3), "8500")
    reconcile(signed_in, bank, date(2026, 3, 5), "8250")
    record(date(2026, 3, 4), bank, make_account("Fruit", "expense"), "40", "Apples")

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 6), "8000"))

    assert "Since the Reconciliation on 3 Mar 2026" in page
    assert "Apples" in page
    assert "Snacks" in page


def test_mismatch_follows_number_format(signed_in: Client, user: User) -> None:
    user.number_format = NumberFormat.INTERNATIONAL
    user.save()
    bank = opening("Bank", "asset", "1500000")

    page = page_text(reconcile(signed_in, bank, date(2026, 3, 3), "1000000"))

    assert "Velora's Balance ₹1,500,000.00" in page
    assert "Off by -₹500,000.00" in page


def test_reconciling_is_blocked_in_privacy_mode(signed_in: Client) -> None:
    bank = bank_with_spending()
    url = account_url("account_reconcile", bank)
    turn_on(signed_in)

    get = signed_in.get(url)
    post = signed_in.post(url, {"date": "2026-03-03", "balance": "8500"})

    for response in (get, post):
        assert response.status_code == 302
        assert response["Location"] == privacy_mode_off_url(url)
    assert not Reconciliation.objects.exists()
