from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.accounts.tests.test_balance import opening, record
from apps.goals.models import Allocation, Goal
from apps.goals.tests.conftest import (
    allocate,
    create_goal,
    edit_allocation,
    goal_text,
    goals_text,
    source,
    text,
)
from apps.investments.models import Instrument
from apps.investments.tests.conftest import add_price, make_broker, record_event

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

FUND = "INF000000001"
STOCK = "INE000000002"


@pytest.fixture
def house(signed_in: Client) -> Goal:
    goal = create_goal(signed_in, "House", "100000")
    assert goal is not None
    return goal


@pytest.fixture
def car(signed_in: Client) -> Goal:
    goal = create_goal(signed_in, "Car", "50000")
    assert goal is not None
    return goal


@pytest.fixture
def broker(signed_in: Client) -> Account:
    """Zerodha: Cash 4000, 10 units of the fund at 150 and 5 shares at 200."""
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    Instrument.objects.create(isin=STOCK, name="Acme Ltd", kind="stock")
    account = make_broker(opening="6000")
    record_event(
        signed_in, account, "buy", FUND, units="10", price="100", amount="1000"
    )
    record_event(
        signed_in, account, "buy", STOCK, units="5", price="200", amount="1000"
    )
    add_price(FUND, date(2026, 3, 5), "150")
    add_price(STOCK, date(2026, 3, 5), "200")
    return account


def fund() -> Instrument:
    return Instrument.objects.get(isin=FUND)


def only_allocation() -> Allocation:
    return Allocation.objects.get()


def test_a_percentage_of_an_account_counts_that_share_of_its_balance(
    signed_in: Client, house: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")

    allocate(signed_in, house, source(bank), percent="25")

    assert "₹5,000.00 of ₹1,00,000.00 · 5%" in goals_text(signed_in)
    assert "Goal Progress ₹5,000.00" in goal_text(signed_in, house)


def test_a_fixed_amount_of_an_account_counts_in_full(
    signed_in: Client, house: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")

    allocate(signed_in, house, source(bank), amount="12000")

    assert "Goal Progress ₹12,000.00" in goal_text(signed_in, house)


def test_progress_follows_the_balance(signed_in: Client, house: Goal) -> None:
    bank = opening("Bank", "asset", "20000")
    cash = opening("Cash", "asset", "0")
    allocate(signed_in, house, source(bank), percent="50")

    record(signed_in, bank, cash, "4000")

    assert "Goal Progress ₹8,000.00" in goal_text(signed_in, house)


def test_an_investment_account_counts_at_market_value(
    signed_in: Client, house: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker), percent="100")

    # Cash 4000, the fund 1500 and the shares 1000.
    assert "Goal Progress ₹6,500.00" in goal_text(signed_in, house)


def test_a_holding_counts_at_its_market_value(
    signed_in: Client, house: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker, fund()), percent="50")

    page = goal_text(signed_in, house)

    assert "Nifty Fund in Zerodha" in page
    assert "Goal Progress ₹750.00" in page


def test_progress_follows_new_prices_without_any_user_action(
    signed_in: Client, house: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker, fund()), percent="100")

    add_price(FUND, date(2026, 3, 6), "180")

    assert "Goal Progress ₹1,800.00" in goal_text(signed_in, house)


def test_allocating_over_all_of_an_account_across_goals_is_refused(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="60")

    response = allocate(signed_in, car, source(bank), percent="50", expect=200)

    assert "Only 40% of Bank is unallocated." in text(response)
    assert Allocation.objects.count() == 1


def test_allocating_over_all_of_a_holding_is_refused(
    signed_in: Client, house: Goal, car: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker, fund()), percent="70.5")

    response = allocate(
        signed_in, car, source(broker, fund()), percent="30", expect=200
    )

    assert "Only 29.5% of Nifty Fund in Zerodha is unallocated." in text(response)


def test_allocating_all_that_is_left_is_allowed(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="60")

    allocate(signed_in, car, source(bank), percent="40")

    assert Allocation.objects.count() == 2


def test_editing_an_allocation_does_not_count_its_old_share(
    signed_in: Client, house: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="60")

    edit_allocation(signed_in, only_allocation(), percent="100")

    assert "Goal Progress ₹20,000.00" in goal_text(signed_in, house)


def test_an_allocation_can_switch_to_a_fixed_amount(
    signed_in: Client, house: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="60")

    edit_allocation(signed_in, only_allocation(), amount="1500")

    assert "Goal Progress ₹1,500.00" in goal_text(signed_in, house)


def test_the_edit_page_shows_the_allocation(signed_in: Client, house: Goal) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="60")

    response = signed_in.get(reverse("allocation_edit", args=[only_allocation().pk]))

    assert "Edit Allocation" in text(response)
    assert f'value="{source(bank)}" selected' in response.content.decode()


def test_an_investment_account_whole_then_a_holding_is_refused(
    signed_in: Client, house: Goal, car: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker), percent="10")

    response = allocate(
        signed_in, car, source(broker, fund()), percent="10", expect=200
    )

    assert "Zerodha is allocated as a whole" in text(response)


def test_a_holding_then_its_investment_account_whole_is_refused(
    signed_in: Client, house: Goal, car: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker, fund()), percent="10")

    response = allocate(signed_in, car, source(broker), percent="10", expect=200)

    assert "Zerodha is allocated through its Holdings" in text(response)


def test_two_holdings_of_one_account_can_be_allocated(
    signed_in: Client, house: Goal, broker: Account
) -> None:
    allocate(signed_in, house, source(broker, fund()), percent="100")
    acme = Instrument.objects.get(isin=STOCK)

    allocate(signed_in, house, source(broker, acme), percent="100")

    assert "Goal Progress ₹2,500.00" in goal_text(signed_in, house)


def test_a_goal_allocates_one_source_once(signed_in: Client, house: Goal) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="10")

    response = allocate(signed_in, house, source(bank), percent="10", expect=200)

    assert "This Goal already has an Allocation of it" in text(response)


@pytest.mark.parametrize(
    "share", [{}, {"percent": "10", "amount": "100"}], ids=["neither", "both"]
)
def test_an_allocation_needs_a_percentage_or_an_amount(
    signed_in: Client, house: Goal, share: dict[str, str]
) -> None:
    bank = opening("Bank", "asset", "20000")

    response = allocate(signed_in, house, source(bank), expect=200, **share)

    assert "Give a percentage or a fixed amount, not both." in text(response)


@pytest.mark.parametrize("percent", ["0", "100.01"])
def test_a_percentage_is_above_0_and_at_most_100(
    signed_in: Client, house: Goal, percent: str
) -> None:
    bank = opening("Bank", "asset", "20000")

    allocate(signed_in, house, source(bank), percent=percent, expect=200)

    assert not Allocation.objects.exists()


def test_an_unknown_source_is_refused(signed_in: Client, house: Goal) -> None:
    response = allocate(signed_in, house, "account:999", percent="10", expect=200)

    assert "Select a valid choice" in text(response)


def test_a_hidden_account_is_not_offered(signed_in: Client, house: Goal) -> None:
    make_account("Old Bank", "asset", hidden=True)
    make_account("Shop", "expense")
    opening("Bank", "asset", "100")

    page = text(signed_in.get(reverse("allocation_create", args=[house.pk])))

    assert "Bank" in page
    assert "Old Bank" not in page
    assert "Shop" not in page


def test_a_fixed_amount_above_its_source_counts_its_value_with_a_warning(
    signed_in: Client, house: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")

    allocate(signed_in, house, source(bank), amount="30000")

    page = goal_text(signed_in, house)
    assert "Goal Progress ₹20,000.00" in page
    assert "Capped: only ₹20,000.00 is there to count." in page
    assert "An Allocation is capped" in goals_text(signed_in)


def test_unallocated_shows_what_every_goal_leaves_of_each_source(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="25")
    allocate(signed_in, car, source(bank), amount="3000")

    page = goal_text(signed_in, house)

    # 20000 less the House's 5000 and the Car's 3000.
    assert "₹12,000.00 75% free" in page


def test_an_allocation_can_be_removed(signed_in: Client, house: Goal) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="25")

    response = signed_in.post(reverse("allocation_delete", args=[only_allocation().pk]))

    assert response["Location"] == reverse("goal_detail", args=[house.pk])
    assert "Nothing allocated yet" in goal_text(signed_in, house)


def test_deleting_a_goal_frees_its_share(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="100")

    signed_in.post(reverse("goal_delete", args=[house.pk]))

    allocate(signed_in, car, source(bank), percent="100")


def test_a_rupee_another_goal_takes_by_percentage_is_not_counted_again(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="75")

    allocate(signed_in, car, source(bank), amount="8000")

    page = goal_text(signed_in, car)
    assert "Goal Progress ₹5,000.00" in page
    assert "Capped: only ₹5,000.00 is there to count." in page
    assert "Goal Progress ₹15,000.00" in goal_text(signed_in, house)


def test_a_later_fixed_amount_counts_only_what_earlier_ones_leave(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), amount="15000")

    allocate(signed_in, car, source(bank), amount="15000")

    assert "Goal Progress ₹15,000.00" in goal_text(signed_in, house)
    assert "Goal Progress ₹5,000.00" in goal_text(signed_in, car)


def test_a_fixed_amount_over_what_is_unallocated_is_saved_with_a_warning(
    signed_in: Client, house: Goal, car: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="75")

    response = signed_in.post(
        reverse("allocation_create", args=[car.pk]),
        {"source": source(bank), "percent": "", "amount": "8000"},
        follow=True,
    )

    assert "Bank has less than that unallocated" in text(response)
    assert Allocation.objects.filter(goal=car).exists()


def test_a_fixed_amount_within_what_is_unallocated_has_no_warning(
    signed_in: Client, house: Goal
) -> None:
    bank = opening("Bank", "asset", "20000")

    response = signed_in.post(
        reverse("allocation_create", args=[house.pk]),
        {"source": source(bank), "percent": "", "amount": "8000"},
        follow=True,
    )

    assert "less than that unallocated" not in text(response)
