from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.net_worth import net_worth_history
from apps.accounts.tests.conftest import make_account
from apps.accounts.tests.test_balance import opening, record
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_one_point_per_month_end_then_today() -> None:
    opening("Bank", "asset", "1000.00")

    points = net_worth_history(date(2026, 4, 10))

    assert [when for when, _ in points] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 10),
    ]
    assert {value for _, value in points} == {Decimal("1000.00")}


def test_points_match_net_worth_as_of_each_date(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1000.00")
    card = opening("Card", "liability", "100.00")
    salary = make_account("Salary", "income")
    record(signed_in, salary, bank, "200.00")
    response = signed_in.post(
        reverse("transaction_create"), form_data(bank, card, "50.00", date="2026-04-15")
    )
    assert response.status_code == 302

    points = dict(net_worth_history(date(2026, 4, 20)))

    assert points[date(2026, 2, 28)] == Decimal("900.00")
    assert points[date(2026, 3, 31)] == Decimal("1100.00")
    assert points[date(2026, 4, 20)] == Decimal("1100.00")


def test_excluded_accounts_are_left_out_of_every_point() -> None:
    opening("Bank", "asset", "1000.00")
    car = opening("Car", "asset", "5000.00")
    car.opening_balance_date = date(2025, 11, 5)
    car.include_in_net_worth = False
    car.save()

    points = net_worth_history(date(2026, 2, 10))

    assert points == [
        (date(2026, 1, 31), Decimal("1000.00")),
        (date(2026, 2, 10), Decimal("1000.00")),
    ]


def test_no_balance_accounts_has_no_points() -> None:
    make_account("Salary", "income")

    assert net_worth_history(date(2026, 4, 10)) == []


def test_today_on_a_month_end_is_one_point() -> None:
    opening("Bank", "asset", "1000.00")

    points = net_worth_history(date(2026, 2, 28))

    assert [when for when, _ in points] == [date(2026, 1, 31), date(2026, 2, 28)]
