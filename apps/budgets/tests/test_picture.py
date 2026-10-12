from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.tests.conftest import make_account
from apps.accounts.tests.test_balance import opening
from apps.budgets.models import set_budget
from apps.budgets.picture import State, budget_picture
from apps.budgets.tests.conftest import JUNE, TODAY, move
from apps.cards.tests.conftest import make_card, make_card_emi
from apps.quick_add.tests.conftest import make_manual_draft
from apps.schedules.occurrences import materialise_occurrences
from apps.schedules.tests.conftest import make_schedule

pytestmark = pytest.mark.django_db


def test_a_budget_shows_its_spent_and_what_is_left() -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(12000), TODAY)
    move(date(2026, 6, 3), bank, groceries, "2500")

    (row,) = budget_picture(JUNE).rows

    assert row.account == groceries
    assert (row.budget, row.spent, row.left) == (
        Decimal(12000),
        Decimal(2500),
        Decimal(9500),
    )


def spent(month: date) -> dict[str, Decimal]:
    return {row.account.name: row.spent for row in budget_picture(month).rows}


def test_spent_counts_only_the_month_less_its_refunds() -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(12000), TODAY)
    move(date(2026, 5, 31), bank, groceries, "900")
    move(date(2026, 6, 1), bank, groceries, "1000")
    move(date(2026, 6, 30), bank, groceries, "500")
    move(date(2026, 6, 20), groceries, bank, "200")
    move(date(2026, 7, 1), bank, groceries, "700")

    assert spent(JUNE) == {"Groceries": Decimal(1300)}


def test_a_refund_bigger_than_the_month_makes_spent_negative() -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(1000), TODAY)
    move(date(2026, 5, 20), bank, groceries, "800")
    move(date(2026, 6, 2), bank, groceries, "100")
    move(date(2026, 6, 3), groceries, bank, "400")

    (row,) = budget_picture(JUNE).rows

    assert (row.spent, row.left) == (Decimal(-300), Decimal(1300))


def test_a_card_emi_purchase_counts_in_full_on_its_date() -> None:
    card = make_card()
    store = make_account("Store", "expense")
    set_budget(store, Decimal(5000), TODAY)
    make_card_emi(card, principal="60000", bought_on=date(2026, 6, 10))
    assert card.pays_from
    move(date(2026, 7, 5), card.pays_from, card, "5400")

    assert spent(JUNE) == {"Store": Decimal(60000)}
    assert spent(date(2026, 7, 1)) == {"Store": Decimal(0)}


def test_transfers_and_drafts_play_no_part() -> None:
    bank = opening("Bank", "asset", "0")
    cash = opening("Cash", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(1000), TODAY)
    move(date(2026, 6, 4), bank, cash, "300")
    make_manual_draft((cash, groceries, "250"), date=date(2026, 6, 5))

    assert spent(JUNE) == {"Groceries": Decimal(0)}


def test_a_hidden_account_keeps_its_budget_and_keeps_counting() -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(1000), date(2026, 5, 1))
    groceries.hidden = True
    groceries.save()
    move(date(2026, 6, 4), bank, groceries, "300")

    assert spent(JUNE) == {"Groceries": Decimal(300)}


@pytest.mark.parametrize(
    ("budget", "spent_amount", "state"),
    [
        ("1000", "0", State.FINE),
        ("1000", "-50", State.FINE),
        ("1000", "899.99", State.FINE),
        ("1000", "900", State.CLOSE),
        ("1000", "1000", State.CLOSE),
        ("1000", "1000.01", State.OVER),
        ("0", "0", State.FINE),
        ("0", "-50", State.FINE),
        ("0", "0.01", State.OVER),
    ],
)
def test_state_is_close_from_90_percent_and_over_past_the_budget(
    budget: str, spent_amount: str, state: State
) -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(budget), TODAY)
    if Decimal(spent_amount) > 0:
        move(date(2026, 6, 10), bank, groceries, spent_amount)
    elif Decimal(spent_amount) < 0:
        move(date(2026, 6, 10), groceries, bank, spent_amount.removeprefix("-"))

    (row,) = budget_picture(JUNE).rows

    assert row.spent == Decimal(spent_amount)
    assert row.state == state


def budgets(month: date) -> dict[str, Decimal]:
    return {row.account.name: row.budget for row in budget_picture(month).rows}


def test_a_change_applies_from_the_start_of_its_month_and_holds_after() -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), date(2026, 4, 20))
    set_budget(groceries, Decimal(11000), date(2026, 6, 2))
    set_budget(groceries, Decimal(12000), TODAY)

    assert budgets(date(2026, 3, 1)) == {}
    assert budgets(date(2026, 4, 1)) == {"Groceries": Decimal(10000)}
    assert budgets(date(2026, 5, 1)) == {"Groceries": Decimal(10000)}
    assert budgets(JUNE) == {"Groceries": Decimal(12000)}
    assert budgets(date(2026, 9, 1)) == {"Groceries": Decimal(12000)}


def test_removing_a_budget_leaves_earlier_months_alone() -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), date(2026, 5, 4))
    set_budget(groceries, Decimal(12000), TODAY)

    set_budget(groceries, None, TODAY)

    assert budgets(date(2026, 5, 1)) == {"Groceries": Decimal(10000)}
    assert budgets(JUNE) == {}
    assert budgets(date(2026, 7, 1)) == {}


def test_a_zero_budget_is_kept_apart_from_no_budget() -> None:
    make_account("Fun", "expense")
    set_budget(make_account("Takeaway", "expense"), Decimal(0), TODAY)

    assert budgets(JUNE) == {"Takeaway": Decimal(0)}


def test_budgets_are_listed_by_name() -> None:
    for name in ("rent", "Groceries", "Fuel"):
        set_budget(make_account(name, "expense"), Decimal(100), TODAY)

    assert list(budgets(JUNE)) == ["Fuel", "Groceries", "rent"]


def test_the_overall_budget_counts_all_spent_including_unbudgeted() -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    fun = make_account("Fun", "expense")
    set_budget(groceries, Decimal(1000), TODAY)
    set_budget(None, Decimal(5000), TODAY)
    move(date(2026, 6, 3), bank, groceries, "1200")
    move(date(2026, 6, 4), bank, fun, "3000")
    move(date(2026, 6, 5), fun, bank, "500")

    picture = budget_picture(JUNE)

    assert picture.unbudgeted == Decimal(2500)
    assert picture.overall
    assert (picture.overall.budget, picture.overall.spent, picture.overall.left) == (
        Decimal(5000),
        Decimal(3700),
        Decimal(1300),
    )


def overall_budget(month: date) -> Decimal | None:
    overall = budget_picture(month).overall
    return overall.budget if overall else None


def test_the_overall_budget_follows_the_same_month_rules() -> None:
    set_budget(None, Decimal(40000), date(2026, 4, 20))
    set_budget(None, Decimal(50000), TODAY)
    set_budget(None, None, date(2026, 8, 3))

    assert overall_budget(date(2026, 3, 1)) is None
    assert overall_budget(date(2026, 5, 1)) == Decimal(40000)
    assert overall_budget(JUNE) == Decimal(50000)
    assert overall_budget(date(2026, 7, 1)) == Decimal(50000)
    assert overall_budget(date(2026, 8, 1)) is None


def test_the_overall_budget_is_not_listed_with_the_budgets() -> None:
    set_budget(None, Decimal(50000), TODAY)

    assert budget_picture(JUNE).rows == []


@pytest.mark.parametrize(
    ("budget", "spent_amount", "state"),
    [
        ("1000", "899.99", State.FINE),
        ("1000", "900", State.CLOSE),
        ("1000", "1000.01", State.OVER),
        ("0", "0", State.FINE),
        ("0", "0.01", State.OVER),
    ],
)
def test_the_overall_budget_is_close_and_over_like_a_budget(
    budget: str, spent_amount: str, state: State
) -> None:
    bank = opening("Bank", "asset", "0")
    set_budget(None, Decimal(budget), TODAY)
    if Decimal(spent_amount):
        move(date(2026, 6, 10), bank, make_account("Fun", "expense"), spent_amount)

    overall = budget_picture(JUNE).overall

    assert overall
    assert overall.state == state


def test_budgets_may_add_up_to_more_than_the_overall_budget() -> None:
    set_budget(make_account("Rent", "expense"), Decimal(30000), TODAY)
    set_budget(make_account("Groceries", "expense"), Decimal(12000), TODAY)

    set_budget(None, Decimal(42000), TODAY)
    assert budget_picture(JUNE).budgets_add_up_to_more is False

    set_budget(None, Decimal("41999.99"), TODAY)
    assert budget_picture(JUNE).budgets_add_up_to_more is True


def test_budgets_add_up_to_more_only_against_an_overall_budget() -> None:
    set_budget(make_account("Rent", "expense"), Decimal(30000), TODAY)

    assert budget_picture(JUNE).budgets_add_up_to_more is False


def test_expected_counts_whats_due_and_waiting_in_the_month() -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    set_budget(rent, Decimal(30000), TODAY)
    make_schedule((bank, rent, "25000"), start_date=date(2026, 6, 28))
    make_manual_draft((bank, rent, "400"), date=date(2026, 6, 2))
    make_manual_draft((bank, rent, "900"), date=date(2026, 7, 1))
    materialise_occurrences(TODAY)

    (row,) = budget_picture(JUNE).rows

    assert row.expected == Decimal(25400)


def test_amountless_occurrences_and_drafts_add_nothing_to_expected() -> None:
    bank = opening("Bank", "asset", "0")
    power = make_account("Power", "expense")
    set_budget(power, Decimal(3000), TODAY)
    make_schedule((bank, power, None), start_date=date(2026, 6, 20))
    make_manual_draft((bank, power, None), date=date(2026, 6, 18))
    materialise_occurrences(TODAY)

    (row,) = budget_picture(JUNE).rows

    assert row.expected == Decimal(0)


def test_expected_never_counts_as_spent_or_moves_the_state() -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    set_budget(rent, Decimal(1000), TODAY)
    move(date(2026, 6, 3), bank, rent, "100")
    make_manual_draft((bank, rent, "5000"), date=date(2026, 6, 20))

    (row,) = budget_picture(JUNE).rows

    assert (row.spent, row.expected, row.left) == (
        Decimal(100),
        Decimal(5000),
        Decimal(900),
    )
    assert row.state == State.FINE


def test_total_expected_includes_unbudgeted_accounts() -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    fun = make_account("Fun", "expense")
    set_budget(rent, Decimal(30000), TODAY)
    make_manual_draft((bank, rent, "25000"), date=date(2026, 6, 28))
    make_manual_draft((bank, fun, "600"), date=date(2026, 6, 10))
    make_manual_draft((bank, fun, "50"), date=date(2026, 5, 31))

    assert budget_picture(JUNE).total_expected == Decimal(25600)
