from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.accounts.merge import AccountMerge
from apps.accounts.models import Account
from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.budgets.models import set_budget
from apps.budgets.tests.conftest import TODAY, move
from apps.schedules.daily_job import run_daily_job
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client


pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("user")]

CLOSE = "Groceries: Spent close to its Budget"
OVER = "Groceries: Spent over its Budget"


def digest_on(day: date) -> str:
    mail.outbox.clear()
    run_daily_job(day)
    return str(mail.outbox[0].body) if mail.outbox else ""


def bank() -> Account:
    """A Bank that can afford the spending, so no low-balance warning shows."""
    account = make_account("Bank", "asset")
    account.opening_balance = Decimal(100000)
    account.save()
    return account


def test_close_then_over_are_each_sent_once_across_several_days() -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), TODAY)
    spender = bank()
    move(date(2026, 6, 10), spender, groceries, "9000")

    first = digest_on(TODAY)

    assert "Budgets" in first
    assert f"15 Jun 2026: {CLOSE}, ₹9,000.00" in first
    assert OVER not in first
    assert CLOSE not in digest_on(date(2026, 6, 16))

    move(date(2026, 6, 17), spender, groceries, "1500")
    later = digest_on(date(2026, 6, 17))
    assert f"17 Jun 2026: {OVER}, ₹10,500.00" in later
    assert CLOSE not in later

    assert "Budgets" not in digest_on(date(2026, 6, 18))


def test_a_budget_going_straight_over_sends_only_the_over_warning() -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), TODAY)
    move(date(2026, 6, 10), bank(), groceries, "12000")

    body = digest_on(TODAY)

    assert f"15 Jun 2026: {OVER}, ₹12,000.00" in body
    assert CLOSE not in body
    assert "Budgets" not in digest_on(date(2026, 6, 16))


def test_a_new_month_starts_fresh() -> None:
    spender = bank()
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), TODAY)
    move(date(2026, 6, 10), spender, groceries, "12000")
    digest_on(TODAY)

    assert "Budgets" not in digest_on(date(2026, 7, 1))

    move(date(2026, 7, 2), spender, groceries, "9500")
    assert f"2 Jul 2026: {CLOSE}, ₹9,500.00" in digest_on(date(2026, 7, 2))


def test_there_is_no_section_when_no_budget_is_close_or_over() -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), TODAY)
    set_budget(None, Decimal(20000), TODAY)
    move(date(2026, 6, 10), bank(), groceries, "8000")

    assert digest_on(TODAY) == ""


def test_the_overall_budget_is_warned_about_once() -> None:
    fun = make_account("Fun", "expense")
    set_budget(None, Decimal(5000), TODAY)
    move(date(2026, 6, 10), bank(), fun, "6000")

    assert "15 Jun 2026: Spent over the Overall Budget, ₹6,000.00" in digest_on(TODAY)
    assert "Budgets" not in digest_on(date(2026, 6, 16))


def test_viewing_the_upcoming_panel_leaves_the_warning_for_the_email(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(timezone, "localdate", lambda *_a, **_k: TODAY)
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), TODAY)
    move(TODAY, bank(), groceries, "12000")

    panel = page_text(signed_in.get(reverse("index")).content.decode())

    assert f"Budgets 15 Jun 2026 {OVER}" in panel
    assert f"16 Jun 2026: {OVER}" in digest_on(date(2026, 6, 16))


def test_merge_hands_sent_warnings_to_a_target_without_a_budget() -> None:
    fun = make_account("Fun", "expense")
    food = make_account("Food", "expense")
    set_budget(fun, Decimal(1000), TODAY)
    move(date(2026, 6, 10), bank(), fun, "1200")
    digest_on(TODAY)

    AccountMerge(source=fun, target=food).run()

    assert "Budgets" not in digest_on(date(2026, 6, 16))


def test_merge_drops_the_source_warnings_when_the_target_has_a_budget() -> None:
    spender = bank()
    fun = make_account("Fun", "expense")
    food = make_account("Food", "expense")
    set_budget(fun, Decimal(1000), TODAY)
    set_budget(food, Decimal(5000), TODAY)
    move(date(2026, 6, 10), spender, fun, "1200")
    move(date(2026, 6, 10), spender, food, "4000")
    digest_on(TODAY)

    AccountMerge(source=fun, target=food).run()

    assert "Food: Spent over its Budget, ₹5,200.00" in digest_on(date(2026, 6, 16))


def test_deleting_an_expense_account_deletes_its_sent_warnings(
    signed_in: Client,
) -> None:
    fun = make_account("Fun", "expense")
    set_budget(fun, Decimal(1000), TODAY)
    move(date(2026, 6, 10), bank(), fun, "1200")
    digest_on(TODAY)
    Transaction.objects.all().delete()

    signed_in.post(account_url("account_delete", fun))

    assert not Account.objects.filter(pk=fun.pk).exists()


def test_a_same_day_rerun_leaves_a_new_warning_for_the_next_digest() -> None:
    spender = bank()
    fun = make_account("Fun", "expense")
    groceries = make_account("Groceries", "expense")
    set_budget(fun, Decimal(1000), TODAY)
    set_budget(groceries, Decimal(10000), TODAY)
    move(date(2026, 6, 10), spender, fun, "1200")
    digest_on(TODAY)

    move(TODAY, spender, groceries, "9000")
    assert digest_on(TODAY) == ""

    assert f"16 Jun 2026: {CLOSE}" in digest_on(date(2026, 6, 16))
