from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.activity import bars, months, rows
from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.accounts.tests.test_account_transactions import record
from apps.accounts.tests.test_balance import opening
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from apps.accounts.activity import Month

pytestmark = pytest.mark.django_db

TODAY = date(2026, 3, 15)


def with_balance(account: Account) -> Account:
    return Account.objects.with_balance().get(pk=account.pk)


def newest_first(account: Account) -> list[Transaction]:
    touching = Split.objects.filter(from_account=account) | Split.objects.filter(
        to_account=account
    )
    return list(
        Transaction.objects.filter(pk__in=touching.values("transaction"))
        .prefetch_related("splits")
        .order_by("-date", "-pk")
    )


def by_month(history: list[Month]) -> dict[str, Month]:
    return {f"{m.start:%Y-%m}": m for m in history}


def test_months_run_twelve_to_this_one_with_month_end_balances() -> None:
    bank = opening("Bank", "asset", "1000")
    rent = make_account("Rent", "expense")
    salary = make_account("Salary", "income")
    record(date(2026, 1, 5), salary, bank, "500", "Pay")
    record(date(2026, 3, 1), bank, rent, "300", "Rent")

    history = months(bank, TODAY)

    assert len(history) == 12
    assert (history[0].start, history[-1].start) == (
        date(2025, 4, 1),
        TODAY.replace(day=1),
    )
    month = by_month(history)
    assert month["2025-12"].balance is None
    assert month["2026-01"].balance == Decimal(1500)
    assert month["2026-02"].balance == Decimal(1500)
    assert (month["2026-03"].moved_out, month["2026-03"].balance) == (
        Decimal(300),
        Decimal(1200),
    )


def test_months_carry_older_moves_into_the_first_balance() -> None:
    bank = opening("Bank", "asset", "1000")
    bank.opening_balance_date = date(2024, 1, 1)
    bank.save()
    rent = make_account("Rent", "expense")
    record(date(2024, 6, 1), bank, rent, "100", "Old rent")

    assert months(bank, TODAY)[0].balance == Decimal(900)


def test_months_read_spending_earning_and_owing_their_usual_way() -> None:
    card = opening("Card", "liability", "0")
    rent = make_account("Rent", "expense")
    salary = make_account("Salary", "income")
    bank = opening("Bank", "asset", "0")
    record(date(2026, 3, 2), card, rent, "250", "Rent")
    record(date(2026, 3, 3), rent, card, "50", "Refund")
    record(date(2026, 3, 4), salary, bank, "900", "Pay")

    assert months(rent, TODAY)[-1].net == Decimal(200)
    assert months(rent, TODAY)[-1].balance is None
    assert months(salary, TODAY)[-1].net == Decimal(900)
    assert months(card, TODAY)[-1].balance == Decimal(200)


def test_bars_sit_on_a_zero_line_that_rises_for_negative_values() -> None:
    bank = opening("Bank", "asset", "300")
    rent = make_account("Rent", "expense")
    record(date(2026, 3, 1), bank, rent, "400", "Rent")

    history = months(bank, TODAY)
    laid_out = bars([m.start for m in history], [m.balance for m in history])

    february, march = laid_out[-2], laid_out[-1]
    assert february.baseline == march.baseline == 75
    assert (february.y, february.height, february.negative) == (0, 75, False)
    assert (march.y, march.height, march.negative) == (75, 25, True)
    assert march.current


def test_rows_give_each_change_and_the_balance_just_after() -> None:
    bank = opening("Bank", "asset", "1000")
    rent = make_account("Rent", "expense")
    salary = make_account("Salary", "income")
    record(date(2026, 3, 1), salary, bank, "500", "Pay")
    record(date(2026, 3, 2), bank, rent, "300", "Rent")
    record(date(2026, 3, 3), bank, rent, "100", "Fees")
    bank = with_balance(bank)

    older = newest_first(bank)[1:]
    result = rows(bank, older)

    assert [(r.change, r.balance_after) for r in result] == [
        (Decimal(-300), Decimal(1200)),
        (Decimal(500), Decimal(1500)),
    ]


def test_rows_for_an_expense_give_what_was_spent_and_no_balance() -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    record(date(2026, 3, 1), bank, rent, "300", "Rent")
    record(date(2026, 3, 2), rent, bank, "20", "Refund")

    result = rows(rent, newest_first(rent))

    assert [(r.change, r.balance_after) for r in result] == [
        (Decimal(-20), None),
        (Decimal(300), None),
    ]
