from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import list_text, make_account
from apps.accounts.tests.test_balance import opening, record
from apps.accounts.tests.test_net_worth import home_text
from apps.goals.models import Allocation
from apps.goals.tests.conftest import (
    allocate,
    create_goal,
    goal_text,
    goals_text,
    source,
    text,
)
from apps.investments.models import Instrument
from apps.investments.tests.conftest import (
    add_price,
    holdings_text,
    make_broker,
    record_event,
)
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.goals.models import Goal

pytestmark = pytest.mark.django_db

FUND = "INF000000001"


def records(client: Client, broker: Account) -> list[str]:
    """Every page whose numbers a Goal must leave alone."""
    return [
        home_text(client),
        list_text(client, "asset"),
        holdings_text(client, broker),
        text(client.get(reverse("budget_list"))),
    ]


def test_goals_change_no_balance_market_value_net_worth_or_budget(
    signed_in: Client,
) -> None:
    bank = opening("Bank", "asset", "20000")
    food = make_account("Food", "expense")
    record(signed_in, bank, food, "500")
    Instrument.objects.create(isin=FUND, name="Nifty Fund", kind="mutual_fund")
    broker = make_broker(opening="5000")
    record_event(signed_in, broker, "buy", FUND, units="10", price="100", amount="1000")
    add_price(FUND, date(2026, 3, 5), "150")
    goals_text(signed_in)  # shows and clears the flash messages so far
    before = records(signed_in, broker)

    goal = create_goal(signed_in, "House", "100000")
    assert goal is not None
    allocate(signed_in, goal, source(bank), percent="100")
    allocate(signed_in, goal, source(broker, Instrument.objects.get()), amount="9999")
    goals_text(signed_in)

    assert records(signed_in, broker) == before


@pytest.fixture
def house(signed_in: Client) -> Goal:
    goal = create_goal(signed_in, "House", "100000")
    assert goal is not None
    return goal


def test_privacy_mode_masks_goal_amounts(signed_in: Client, house: Goal) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), amount="30000")
    turn_on(signed_in)

    for page in (goals_text(signed_in), goal_text(signed_in, house)):
        assert "₹••••" in page
        assert "20,000" not in page
        assert "1,00,000" not in page


def test_privacy_mode_blocks_editing(signed_in: Client, house: Goal) -> None:
    bank = opening("Bank", "asset", "20000")
    allocate(signed_in, house, source(bank), percent="25")
    turn_on(signed_in)

    for url in (
        reverse("goal_edit", args=[house.pk]),
        reverse("allocation_edit", args=[Allocation.objects.get().pk]),
    ):
        assert signed_in.get(url).status_code != 200
