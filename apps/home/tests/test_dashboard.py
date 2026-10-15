from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forecast import DAYS, forecast
from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card
from apps.home import dashboard
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import DjangoAssertNumQueries

    from apps.accounts.forecast import Forecast
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

TODAY = date(2026, 6, 15)


def move(when: date, source: Account, destination: Account, amount: str) -> None:
    transaction = Transaction.objects.create(date=when)
    Split.objects.create(
        transaction=transaction,
        from_account=source,
        to_account=destination,
        amount=Decimal(amount),
    )


def test_cash_flow_counts_earned_and_spent_but_not_transfers() -> None:
    bank = opening("Bank", "asset", "0")
    cash = opening("Cash", "asset", "0")
    salary = make_account("Salary", "income")
    rent = make_account("Rent", "expense")
    move(date(2026, 5, 1), salary, bank, "1000")
    move(date(2026, 5, 3), bank, rent, "400")
    move(date(2026, 6, 2), bank, cash, "50")
    move(date(2026, 6, 3), bank, rent, "100")
    move(date(2026, 6, 4), rent, bank, "30")

    flows = dashboard.cash_flow(TODAY, count=3)

    assert [flow.start for flow in flows] == [
        date(2026, 4, 1),
        date(2026, 5, 1),
        date(2026, 6, 1),
    ]
    may, june = flows[1], flows[2]
    assert (may.earned, may.spent, may.saved) == (
        Decimal(1000),
        Decimal(400),
        Decimal(600),
    )
    assert may.savings_rate == 60
    assert (june.earned, june.spent) == (Decimal(0), Decimal(70))
    assert june.savings_rate is None


def test_spent_by_now_last_month_stops_at_the_same_day() -> None:
    bank = opening("Bank", "asset", "0")
    food = make_account("Food", "expense")
    move(date(2026, 5, 15), bank, food, "10")
    move(date(2026, 5, 16), bank, food, "99")

    assert dashboard.spent_by_now_last_month(TODAY) == 10


def test_spending_shows_the_biggest_then_folds_the_rest_into_other() -> None:
    bank = opening("Bank", "asset", "0")
    for index, amount in enumerate(["600", "100", "90", "80", "70", "40", "20"]):
        move(TODAY, bank, make_account(f"Expense {index}", "expense"), amount)
    last_month = make_account("Only last month", "expense")
    move(date(2026, 5, 20), bank, last_month, "500")

    slices = dashboard.spending(TODAY)

    assert [s.name for s in slices] == [
        "Expense 0",
        "Expense 1",
        "Expense 2",
        "Expense 3",
        "Expense 4",
        "2 more",
    ]
    assert slices[-1].total == 60
    assert slices[-1].url == ""
    assert slices[0].percent == 60
    assert slices[1].x == 60
    assert sum(s.percent for s in slices) == pytest.approx(100)


def test_cards_show_the_latest_closed_statement_and_limit_used() -> None:
    bank = opening("Bank", "asset", "0")
    card = opening("Card", "liability", "750")
    card.statement_day, card.due_day, card.pays_from = 5, 25, bank
    card.low_balance_threshold = Decimal(1000)
    card.save()
    make_account("Loan", "liability")
    for end in (date(2026, 5, 5), date(2026, 6, 5)):
        Statement.objects.create(
            card=card,
            period_start=end.replace(month=end.month - 1, day=6),
            period_end=end,
            due_date=end.replace(day=25),
            estimated_amount=Decimal(100),
        )

    rows = dashboard.cards(TODAY)

    assert [row.card for row in rows] == [card]
    statement = rows[0].statement
    assert statement is not None
    assert statement.period_end == date(2026, 6, 5)
    assert rows[0].limit_percent == 75


def test_cards_fetch_only_the_latest_statement(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    card = make_card()
    for end in (date(2026, 3, 15), date(2026, 5, 15), date(2026, 4, 15)):
        Statement.objects.create(
            card=card,
            period_start=end - timedelta(days=30),
            period_end=end,
            due_date=end + timedelta(days=20),
            estimated_amount=Decimal(100),
        )

    with django_assert_num_queries(2):
        rows = dashboard.cards(TODAY)

    statement = rows[0].statement
    assert statement is not None
    assert statement.period_end == date(2026, 5, 15)


def test_cards_show_nothing_to_pay_for_a_zero_statement(signed_in: Client) -> None:
    card = make_card()
    due = timezone.localdate() - timedelta(days=3)
    Statement.objects.create(
        card=card,
        period_start=due - timedelta(days=50),
        period_end=due - timedelta(days=20),
        due_date=due,
        estimated_amount=Decimal(0),
    )

    text = page_text(signed_in.get(reverse("index")).content.decode())

    assert "Nothing to pay" in text
    assert "overdue" not in text


def test_net_worth_change_runs_from_the_start_of_the_range() -> None:
    bank = opening("Bank", "asset", "1000")
    bank.opening_balance_date = date(2025, 1, 1)
    bank.save()
    salary = make_account("Salary", "income")
    move(date(2025, 3, 1), salary, bank, "500")
    move(date(2026, 6, 1), salary, bank, "250")

    six_months = dashboard.net_worth_card(TODAY, 6, charted=True)
    everything = dashboard.net_worth_card(TODAY, None, charted=True)

    assert six_months.since == six_months.history[0][0]
    assert six_months.change == 250
    assert six_months.change_percent == Decimal("16.7")
    assert everything.since == date(2025, 1, 31)
    assert everything.change == 750
    assert everything.history[-1] == (TODAY, Decimal(1750))
    assert everything.chart is not None


def test_net_worth_change_is_since_last_month_end_without_history() -> None:
    bank = opening("Bank", "asset", "1000")
    move(date(2026, 6, 1), make_account("Salary", "income"), bank, "250")

    card = dashboard.net_worth_card(TODAY, 12, charted=False)

    assert card.since == date(2026, 5, 31)
    assert card.change == 250
    assert card.change_percent == 25


@pytest.mark.parametrize("months", [6, 12, None])
@pytest.mark.parametrize("charted", [True, False])
def test_net_worth_card_query_count_is_fixed(
    django_assert_max_num_queries: DjangoAssertNumQueries,
    months: int | None,
    charted: bool,  # noqa: FBT001
) -> None:
    bank = opening("Bank", "asset", "1000")
    bank.opening_balance_date = date(2023, 1, 1)
    bank.save()
    move(date(2024, 5, 1), make_account("Salary", "income"), bank, "250")

    with django_assert_max_num_queries(3):
        dashboard.net_worth_card(TODAY, months, charted=charted)


def test_home_page_builds_the_forecast_once(
    signed_in: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[date] = []

    def spy(start: date, length: int = DAYS) -> Forecast:
        calls.append(start)
        return forecast(start, length)

    monkeypatch.setattr("apps.home.views.forecast", spy)
    monkeypatch.setattr("apps.digest.upcoming.forecast", spy)
    opening("Bank", "asset", "1000")

    signed_in.get(reverse("index"))

    assert len(calls) == 1


def test_net_worth_card_skips_history_when_uncharted() -> None:
    opening("Bank", "asset", "1000")

    card = dashboard.net_worth_card(TODAY, None, charted=False)

    assert card.history == []
    assert card.chart is None


def test_home_page_shows_each_section(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000")
    salary = make_account("Salary", "income")
    groceries = make_account("Groceries", "expense")
    today = timezone.localdate()
    move(today, salary, bank, "500")
    move(today, bank, groceries, "125")

    text = page_text(signed_in.get(reverse("index")).content.decode())

    assert "Earned ₹500.00" in text
    assert "Spent ₹125.00" in text
    assert "Saved ₹375.00" in text
    assert "Savings rate 75%" in text
    assert "Groceries" in text
    assert "Earned and spent" in text
    assert "Recent Transactions" in text
    assert "Next 30 days" in text


@pytest.mark.parametrize(("raw", "active"), [("6m", "6m"), ("bogus", "1y")])
def test_range_picks_the_net_worth_history_span(
    signed_in: Client, raw: str, active: str
) -> None:
    opening("Bank", "asset", "1000")

    page = signed_in.get(reverse("index"), {"range": raw}).content.decode()

    assert f'href="?range={active}" aria-current="page"' in page
