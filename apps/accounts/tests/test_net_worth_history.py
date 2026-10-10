import re
from datetime import date, datetime
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import edit_account, make_account
from apps.accounts.tests.test_balance import opening, record
from apps.accounts.tests.test_net_worth import home_page
from apps.transactions.tests.conftest import form_data

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.test import Client
    from pytest_django import DjangoAssertNumQueries

    type SetToday = Callable[[date], None]

pytestmark = pytest.mark.django_db

POINT_ROW = re.compile(r"<tr><td>([^<]+)</td><td>₹([^<]+)</td></tr>")


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> SetToday:
    def set_today(when: date) -> None:
        monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: when)

    return set_today


def history(client: Client) -> list[tuple[str, str]]:
    return POINT_ROW.findall(home_page(client))


def test_one_point_per_month_end_then_today(signed_in: Client, today: SetToday) -> None:
    opening("Bank", "asset", "1000.00")
    today(date(2026, 4, 10))

    assert history(signed_in) == [
        ("31 Jan 2026", "1,000.00"),
        ("28 Feb 2026", "1,000.00"),
        ("31 Mar 2026", "1,000.00"),
        ("10 Apr 2026", "1,000.00"),
    ]


def test_points_match_net_worth_as_of_each_date(
    signed_in: Client, today: SetToday
) -> None:
    bank = opening("Bank", "asset", "1000.00")
    card = opening("Card", "liability", "100.00")
    salary = make_account("Salary", "income")
    record(signed_in, salary, bank, "200.00")
    response = signed_in.post(
        reverse("transaction_create"), form_data(bank, card, "50.00", date="2026-04-15")
    )
    assert response.status_code == 302
    today(date(2026, 4, 20))

    points = history(signed_in)

    assert [value for _, value in points] == [
        "900.00",
        "900.00",
        "1,100.00",
        "1,100.00",
    ]
    for when, value in points:
        as_of = datetime.strptime(when, "%d %b %Y").date().isoformat()  # noqa: DTZ007
        assert f"Net Worth ₹{value}" in home_page(signed_in, as_of=as_of)


def test_excluded_accounts_are_left_out_of_every_point(
    signed_in: Client, today: SetToday
) -> None:
    opening("Bank", "asset", "1000.00")
    car = opening("Car", "asset", "5000.00")
    edit_account(
        signed_in,
        car,
        opening_balance_date=date(2025, 11, 5),
        include_in_net_worth=False,
    )
    today(date(2026, 2, 10))

    assert history(signed_in) == [
        ("31 Jan 2026", "1,000.00"),
        ("10 Feb 2026", "1,000.00"),
    ]


def test_today_on_a_month_end_is_one_point(signed_in: Client, today: SetToday) -> None:
    opening("Bank", "asset", "1000.00")
    today(date(2026, 2, 28))

    assert history(signed_in) == [
        ("31 Jan 2026", "1,000.00"),
        ("28 Feb 2026", "1,000.00"),
    ]


def test_no_balance_accounts_has_no_points(signed_in: Client) -> None:
    make_account("Salary", "income")

    assert history(signed_in) == []


@pytest.mark.parametrize("accounts", [2, 6])
def test_home_page_query_count_does_not_grow_with_accounts(
    signed_in: Client,
    today: SetToday,
    django_assert_num_queries: DjangoAssertNumQueries,
    accounts: int,
) -> None:
    salary = make_account("Salary", "income")
    for i in range(accounts):
        kind = "asset" if i % 2 == 0 else "liability"
        account = opening(f"Account {i}", kind, "100.00")
        record(signed_in, salary, account, "10.00")
    today(date(2026, 6, 15))

    with django_assert_num_queries(22):
        signed_in.get(reverse("index"))
