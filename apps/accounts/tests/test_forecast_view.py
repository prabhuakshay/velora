from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.forecast import forecast
from apps.accounts.forecast_view import chart, scope_for, timeline, worst
from apps.accounts.tests.conftest import make_account
from apps.cards.tests.conftest import make_card, record
from apps.quick_add.tests.conftest import make_manual_draft

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 1)


def test_all_assets_add_up_and_a_transfer_between_them_moves_nothing() -> None:
    savings = make_account("Savings", "asset")
    wallet = make_account("Wallet", "asset")
    savings.opening_balance = Decimal(1000)
    savings.save()
    make_manual_draft((savings, wallet, "400"), description="Cash out")
    result = forecast(TODAY)

    scope = scope_for(result, None)
    [day] = timeline(scope, result)

    assert scope.now == Decimal(1000)
    assert scope.balances[-1] == Decimal(1000)
    [entry] = day.entries
    assert (entry.label, entry.change, entry.accounts) == (
        "Cash out",
        Decimal(0),
        ["Savings → Wallet"],
    )


def test_a_card_bill_is_an_estimate_linking_to_the_card() -> None:
    savings = make_account("Bank", "asset")
    card = make_card(pays_from=savings)
    record(card, make_account("Groceries", "expense"), "12000", date(2026, 10, 3))
    result = forecast(date(2026, 10, 10))

    [day] = timeline(scope_for(result, None), result)

    [entry] = day.entries
    assert (day.day, entry.label, entry.change, entry.estimated) == (
        date(2026, 11, 5),
        "HDFC card bill",
        Decimal(-12000),
        True,
    )
    assert entry.url.endswith(f"/accounts/liability/{card.pk}/")


def test_the_worst_day_of_a_card_is_when_it_owes_most() -> None:
    card = make_account("Card", "liability")
    make_manual_draft((card, make_account("Travel", "expense"), "1500"))
    result = forecast(TODAY)

    assert worst(scope_for(result, card.pk), result) == (
        date(2026, 10, 8),
        Decimal(1500),
    )


def test_the_chart_marks_zero_and_the_threshold() -> None:
    savings = make_account("Bank", "asset")
    savings.opening_balance = Decimal(100)
    savings.low_balance_threshold = Decimal(50)
    savings.save()
    make_manual_draft((savings, make_account("Rent", "expense"), "200"))
    result = forecast(TODAY)
    scope = scope_for(result, savings.pk)

    drawn = chart(scope, result, timeline(scope, result))

    assert drawn["zero"] == pytest.approx(160 * 100 / 200)
    assert drawn["threshold"] == pytest.approx(160 * 50 / 200)
