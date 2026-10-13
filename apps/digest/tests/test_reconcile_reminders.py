from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Reconciliation
from apps.accounts.tests.conftest import account_url, make_account
from apps.accounts.tests.test_account_transactions import record
from apps.digest.upcoming import RECONCILE_DAYS, Section, upcoming
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings

    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 13)


def days_ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def paid_in(account: Account, when: date, amount: str = "1000") -> None:
    salary = make_account(f"Salary {account} {when} {amount}", "income")
    record(when, salary, account, amount, "Pay")


def reconciled(account: Account, when: date, balance: str) -> None:
    Reconciliation.objects.create(account=account, date=when, balance=Decimal(balance))


def reconcile_items(today: date = TODAY) -> list[str]:
    sections = [s for s in upcoming(today, warned=[]) if s.title == "Reconcile"]
    return [item.label for section in sections for item in section.items]


def section(today: date = TODAY) -> Section:
    [found] = [s for s in upcoming(today, warned=[]) if s.title == "Reconcile"]
    return found


def test_the_interval_is_thirty_days() -> None:
    assert RECONCILE_DAYS == 30


def test_an_account_never_reconciled_is_listed() -> None:
    bank = make_account("Bank", "asset")
    paid_in(bank, days_ago(5))

    [item] = section().items

    assert item.label == "Bank, never reconciled"
    assert item.amount == Decimal(1000)
    assert item.url == account_url("account_reconcile", bank)


def test_an_account_reconciled_over_thirty_days_ago_is_listed() -> None:
    card = make_account("Card", "liability")
    record(days_ago(40), card, make_account("Food", "expense"), "200", "Lunch")
    reconciled(card, days_ago(30), "200")
    record(days_ago(2), card, make_account("Fuel", "expense"), "500", "Fuel")

    [item] = section().items

    assert item.label == "Card, not reconciled since 13 Sep 2026"
    assert item.amount == Decimal(700)
    assert item.url == account_url("account_reconcile", card)


def test_a_liability_in_credit_is_listed_as_in_credit() -> None:
    card = make_account("Card", "liability")
    record(days_ago(5), make_account("Refunds", "income"), card, "300", "Refund")

    [item] = section().items

    assert item.label == "Card, never reconciled, in credit"
    assert item.amount == Decimal(300)


def test_an_account_reconciled_within_thirty_days_is_not_listed() -> None:
    bank = make_account("Bank", "asset")
    paid_in(bank, days_ago(10))
    reconciled(bank, days_ago(29), "0")

    assert reconcile_items() == []


def test_hidden_and_dormant_accounts_are_not_listed() -> None:
    paid_in(make_account("Old savings", "asset", hidden=True), days_ago(3))
    paid_in(make_account("Closed loan", "liability"), days_ago(31))
    paid_in(make_account("Rent", "expense"), days_ago(3))

    assert reconcile_items() == []


def test_a_latest_reconciliation_that_is_off_is_listed_with_the_difference() -> None:
    bank = make_account("Bank", "asset")
    paid_in(bank, date(2026, 3, 1))
    reconciled(bank, date(2026, 3, 3), "1000")
    paid_in(bank, date(2026, 3, 2), "40")

    [item] = section().items

    assert item.label == "Bank: Reconciliation on 3 Mar 2026 is off by"
    assert item.amount == Decimal(-40)
    assert item.url == account_url("account_reconcile", bank)


def test_a_recent_reconciliation_that_is_off_is_listed() -> None:
    bank = make_account("Bank", "asset")
    paid_in(bank, days_ago(5))
    reconciled(bank, days_ago(3), "900")

    assert reconcile_items() == ["Bank: Reconciliation on 10 Oct 2026 is off by"]


def test_an_older_reconciliation_off_behind_a_matching_one_is_not_listed() -> None:
    bank = make_account("Bank", "asset")
    paid_in(bank, days_ago(5))
    reconciled(bank, days_ago(6), "500")
    reconciled(bank, days_ago(3), "1000")

    assert reconcile_items() == []


def test_a_hidden_account_off_is_not_listed() -> None:
    bank = make_account("Bank", "asset", hidden=True)
    paid_in(bank, days_ago(5))
    reconciled(bank, days_ago(3), "900")

    assert reconcile_items() == []


def test_finding_accounts_to_reconcile_takes_the_same_queries_as_they_grow() -> None:
    def add_account(n: int) -> None:
        bank = make_account(f"Bank {n}", "asset")
        paid_in(bank, days_ago(40))
        reconciled(bank, days_ago(35), "1000")
        reconciled(bank, days_ago(31), "999")
        paid_in(bank, days_ago(2))

    add_account(1)
    with CaptureQueriesContext(connection) as one:
        assert len(section().items) == 1
    for n in range(2, 6):
        add_account(n)
    with CaptureQueriesContext(connection) as five:
        assert len(section().items) == 5

    assert len(five) == len(one)


def test_the_upcoming_panel_shows_the_difference_privately(
    signed_in: Client, user: User
) -> None:
    today = timezone.localdate()
    bank = make_account("Bank", "asset")
    paid_in(bank, today - timedelta(days=5))
    reconciled(bank, today - timedelta(days=3), "960")
    off = f"Reconciliation on {today - timedelta(days=3):%-d %b %Y} is off by"

    page = signed_in.get(reverse("index")).content.decode()
    assert off in page
    assert "-₹40.00" in page
    assert f'href="{account_url("account_reconcile", bank)}"' in page

    user.set_privacy_mode(on=True)
    page = signed_in.get(reverse("index")).content.decode()
    assert off in page
    assert "40.00" not in page


@pytest.mark.usefixtures("user")
def test_the_digest_includes_the_reconcile_section(settings: Settings) -> None:
    settings.SITE_URL = "https://velora.example"
    bank = make_account("Bank", "asset")
    paid_in(bank, days_ago(5))
    reconciled(bank, days_ago(3), "960")
    card = make_account("Card", "liability")
    record(days_ago(4), card, make_account("Food", "expense"), "200", "Lunch")

    run_daily_job(TODAY)

    [email] = mail.outbox
    assert "Reconcile" in email.body
    assert "Bank: Reconciliation on 10 Oct 2026 is off by, -₹40.00" in email.body
    assert "Card, never reconciled, ₹200.00" in email.body
    assert "https://velora.example" + account_url("account_reconcile", card) in (
        email.body
    )
