from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.cards.plans import Plan
from apps.cards.tests.conftest import make_card_emi

if TYPE_CHECKING:
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def test_a_no_cost_emi_costs_nothing_more(card: Account) -> None:
    plan = Plan.of(make_card_emi(card, principal="1200", annual_rate="0"))

    assert (plan.monthly, plan.interest, plan.cost, plan.total) == (
        Decimal(100),
        Decimal(0),
        Decimal(0),
        Decimal(1200),
    )
    assert plan.ends == date(2027, 8, 15)
    assert plan.next == plan.rows[0]


def test_installments_up_to_today_are_billed_and_the_next_is_marked(
    card: Account,
) -> None:
    plan = Plan.of(make_card_emi(card), date(2026, 10, 20))

    assert [row.state for row in plan.rows[:4]] == [
        "billed",
        "billed",
        "next",
        "upcoming",
    ]
    assert plan.billed == 2


def test_a_foreclosure_bills_the_rest_and_saves_the_interest_left(
    card: Account,
) -> None:
    emi = make_card_emi(card)
    emi.foreclosed_on = date(2026, 10, 20)
    emi.foreclosure_fee = Decimal(1000)
    plan = Plan.of(emi, date(2026, 10, 20))

    schedule = emi.installments()
    left = schedule[2:]
    foreclosure = plan.foreclosure
    assert foreclosure is not None
    assert foreclosure.closing == date(2026, 11, 15)
    assert foreclosure.remaining == sum(item.principal for item in left)
    assert foreclosure.saved == sum(item.interest + item.gst for item in left)
    assert foreclosure.net == foreclosure.saved - 1000
    assert plan.fees == Decimal(1000)
    assert plan.ends == date(2026, 11, 15)
    assert {row.state for row in plan.rows[2:]} == {"cancelled"}
