from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, strip_tags

from apps.accounts.activity import month_end
from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.budgets.models import Budget, set_budget
from apps.budgets.tests.conftest import move
from apps.quick_add.tests.conftest import make_manual_draft
from apps.users.tests.conftest import privacy_mode_off_url, turn_on
from apps.users.tests.test_privacy_mode import MASK

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def budgets_text(client: Client) -> str:
    return page_text(client.get(reverse("budget_list")).content.decode())


def set_on(client: Client, account: Account, amount: str) -> str:
    response = client.post(
        reverse("budget_set"), {"account": account.pk, "amount": amount}
    )
    if response.status_code == 302:
        assert response["Location"] == reverse("budget_list")
        return ""
    return page_text(response.content.decode())


def test_the_budgets_page_is_in_the_navigation(signed_in: Client) -> None:
    page = signed_in.get(reverse("index")).content.decode()

    assert f'href="{reverse("budget_list")}"' in page


def test_each_budget_shows_budget_spent_and_left(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    move(today, bank, groceries, "2500")
    set_on(signed_in, groceries, "12000")

    text = budgets_text(signed_in)

    assert "Groceries" in text
    assert "Budget ₹12,000.00" in text
    assert "Spent ₹2,500.00" in text
    assert "₹9,500.00 left" in text


def test_each_budget_shows_what_is_expected(signed_in: Client) -> None:
    today = timezone.localdate()
    rent = make_account("Rent", "expense")
    make_manual_draft((opening("Bank", "asset", "0"), rent, "25000"), date=today)
    set_on(signed_in, rent, "30000")

    assert "Expected ₹25,000.00" in budgets_text(signed_in)


def test_each_row_links_to_the_months_transactions(signed_in: Client) -> None:
    today = timezone.localdate()
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(100), today)
    start = today.replace(day=1)
    query = urlencode(
        {"account": groceries.pk, "start": start, "end": month_end(start)}
    )

    page = signed_in.get(reverse("budget_list")).content.decode()

    assert escape(f"{reverse('transaction_list')}?{query}") in page


def test_changing_a_budget_replaces_it(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")

    set_on(signed_in, groceries, "15000")

    text = budgets_text(signed_in)
    assert "Budget ₹15,000.00" in text
    assert "₹12,000.00" not in text


def test_the_change_form_starts_from_the_current_budget(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")

    page = signed_in.get(
        reverse("budget_set") + f"?account={groceries.pk}"
    ).content.decode()

    assert 'value="12000.00"' in page
    assert reverse("budget_remove", args=[groceries.pk]) in page


def test_removing_a_budget_drops_it_from_the_page(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")

    response = signed_in.post(reverse("budget_remove", args=[groceries.pk]))

    assert response["Location"] == reverse("budget_list")
    text = budgets_text(signed_in)
    assert "Removed the Budget for Groceries from this month on." in text
    assert "No Budgets yet" in text


def test_a_zero_budget_is_over_at_any_spent(signed_in: Client) -> None:
    today = timezone.localdate()
    takeaway = make_account("Takeaway", "expense")
    set_on(signed_in, takeaway, "0")
    move(today, opening("Bank", "asset", "0"), takeaway, "1")

    text = budgets_text(signed_in)

    assert "Budget ₹0.00" in text
    assert "Over" in text


def test_a_budget_close_to_its_limit_is_marked_close(signed_in: Client) -> None:
    today = timezone.localdate()
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "1000")
    move(today, opening("Bank", "asset", "0"), groceries, "950")

    assert "Close" in budgets_text(signed_in)


def test_a_negative_amount_is_refused(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    text = set_on(signed_in, groceries, "-1")

    assert "Enter 0 or more." in text
    assert "Groceries" not in budgets_text(signed_in)


@pytest.mark.parametrize("kind", ["asset", "liability", "income"])
def test_only_expense_accounts_are_offered(signed_in: Client, kind: str) -> None:
    other = make_account("Elsewhere", kind)
    make_account("Groceries", "expense")

    page = page_text(signed_in.get(reverse("budget_set")).content.decode())
    text = set_on(signed_in, other, "100")

    assert "Groceries" in page
    assert "Elsewhere" not in page
    assert "Select a valid choice." in text
    assert "Elsewhere" not in budgets_text(signed_in)


def test_the_database_refuses_a_negative_budget() -> None:
    groceries = make_account("Groceries", "expense")

    with pytest.raises(IntegrityError, match="budgets_budget_amount_not_negative"):
        set_budget(groceries, Decimal(-1), timezone.localdate())


def test_amounts_follow_the_number_format(signed_in: Client, user: User) -> None:
    user.number_format = "international"
    user.save()
    set_on(signed_in, make_account("Rent", "expense"), "120000")

    assert "Budget ₹120,000.00" in budgets_text(signed_in)


def test_privacy_mode_masks_every_amount(signed_in: Client) -> None:
    today = timezone.localdate()
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")
    move(today, opening("Bank", "asset", "0"), groceries, "13000")
    turn_on(signed_in)

    page = signed_in.get(reverse("budget_list")).content.decode()

    text = page_text(page)
    assert f"Budget {strip_tags(MASK)}" in text
    assert f"Spent {strip_tags(MASK)}" in text
    assert f"Expected {strip_tags(MASK)}" in text
    assert "12,000" not in page
    assert "13,000" not in page
    assert "1,000" not in page
    assert "text-red-600" not in page


def test_privacy_mode_blocks_the_budget_form(signed_in: Client) -> None:
    turn_on(signed_in)
    url = reverse("budget_set")

    response = signed_in.get(url)

    assert response["Location"] == privacy_mode_off_url(url)


def test_change_history_records_budget_changes(superuser: User) -> None:
    client = Client()
    client.force_login(superuser)
    groceries = make_account("Groceries", "expense")
    set_on(client, groceries, "12000")
    set_on(client, groceries, "15000")
    budget = Budget.objects.get()

    page = client.get(reverse("admin:budgets_budget_history", args=[budget.pk]))

    text = page_text(page.content.decode())
    assert text.count(superuser.email) >= 2
