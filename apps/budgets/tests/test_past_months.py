from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.budgets.models import set_budget
from apps.budgets.picture import budget_picture
from apps.budgets.tests.conftest import cell, move
from apps.budgets.tests.test_budgets_page import (
    budgets_page,
    budgets_text,
    edit_url,
    set_on,
)
from apps.budgets.urls import urlpatterns

if TYPE_CHECKING:
    from django.test import Client
    from django.urls import URLPattern

pytestmark = pytest.mark.django_db


def this_month() -> date:
    return timezone.localdate().replace(day=1)


def last_month() -> date:
    return (this_month() - timedelta(days=1)).replace(day=1)


def month_url(month: date) -> str:
    return f"{reverse('budget_list')}?month={month:%Y-%m}"


def test_a_past_month_shows_the_budget_it_had_against_its_spent(
    signed_in: Client,
) -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(10000), last_month())
    set_budget(groceries, Decimal(12000), timezone.localdate())
    move(last_month(), opening("Bank", "asset", "0"), groceries, "2500")

    text = page_text(signed_in.get(month_url(last_month())).content.decode())

    assert f"{last_month():%B %Y}" in text
    assert "Groceries Budget ₹10,000.00 Spent ₹2,500.00" in text
    assert "₹12,000.00" not in text


def test_a_mid_month_change_reaches_back_to_the_first_and_no_further() -> None:
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    fuel = make_account("Fuel", "expense")
    set_budget(groceries, Decimal(10000), date(2026, 5, 10))
    set_budget(fuel, Decimal(3000), date(2026, 5, 10))
    move(date(2026, 5, 31), bank, groceries, "2500")
    move(date(2026, 6, 1), bank, groceries, "400")
    move(date(2026, 5, 2), bank, fuel, "900")

    set_budget(groceries, Decimal(12000), date(2026, 6, 20))
    set_budget(fuel, None, date(2026, 6, 20))

    may = [
        (row.account.name, row.budget, row.spent)
        for row in budget_picture(date(2026, 5, 1)).rows
    ]
    june = [
        (row.account.name, row.budget, row.spent)
        for row in budget_picture(date(2026, 6, 1)).rows
    ]
    assert may == [
        ("Fuel", Decimal(3000), Decimal(900)),
        ("Groceries", Decimal(10000), Decimal(2500)),
    ]
    assert june == [("Groceries", Decimal(12000), Decimal(400))]


def next_month() -> date:
    return (this_month() + timedelta(days=31)).replace(day=1)


def test_this_month_links_back_but_not_forward(signed_in: Client) -> None:
    page = signed_in.get(reverse("budget_list")).content.decode()

    assert f'href="{month_url(last_month())}"' in page
    assert f"month={next_month():%Y-%m}" not in page


def test_a_past_month_links_both_ways(signed_in: Client) -> None:
    before = (last_month() - timedelta(days=1)).replace(day=1)

    page = signed_in.get(month_url(last_month())).content.decode()

    assert f'href="{month_url(before)}"' in page
    assert f'href="{month_url(this_month())}"' in page


def test_a_past_month_lists_only_its_budgets_read_only(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    make_account("Fuel", "expense")
    set_budget(groceries, Decimal(10000), last_month())
    set_on(signed_in, groceries, "")

    page = signed_in.get(month_url(last_month())).content.decode()

    assert "Groceries Budget ₹10,000.00" in page_text(page)
    assert "Fuel" not in page_text(page)
    assert cell(page, "Budget for Groceries") is None
    assert edit_url(groceries) not in page


def test_this_month_offers_the_cells(signed_in: Client) -> None:
    set_budget(make_account("Groceries", "expense"), Decimal(100), this_month())

    page = signed_in.get(reverse("budget_list")).content.decode()

    assert cell(page, "Budget for Groceries") == "100"


# Every Budgets route but the page itself edits, so each must refuse a past month.
EDITS = [route for route in urlpatterns if route.name != "budget_list"]


@pytest.mark.parametrize("route", EDITS, ids=lambda route: route.name)
@pytest.mark.parametrize("method", ["get", "post"])
def test_an_edit_sent_for_a_past_month_is_refused(
    signed_in: Client, route: URLPattern, method: str
) -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, Decimal(100), this_month())
    url = reverse(
        route.name or "", kwargs=dict.fromkeys(route.pattern.converters, groceries.pk)
    )

    response = getattr(signed_in, method)(
        url,
        {"account": groceries.pk, "amount": "500", "month": f"{last_month():%Y-%m}"},
    )

    assert response["Location"] == reverse("budget_list")
    page = signed_in.get(reverse("budget_list")).content.decode()
    assert "Budgets can be changed only for this month." in page_text(page)
    assert cell(page, "Budget for Groceries") == "100"


def test_a_cell_saved_for_a_past_month_reloads_the_page(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    response = signed_in.post(
        edit_url(groceries),
        {"amount": "500", "month": f"{last_month():%Y-%m}"},
        headers={"HX-Request": "true"},
    )

    assert response["HX-Redirect"] == reverse("budget_list")
    text = budgets_text(signed_in)
    assert "Budgets can be changed only for this month." in text
    assert cell(budgets_page(signed_in), "Budget for Groceries") == ""


def test_an_edit_sent_for_this_month_goes_through(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    signed_in.post(
        edit_url(groceries), {"amount": "500", "month": f"{this_month():%Y-%m}"}
    )

    assert cell(budgets_page(signed_in), "Budget for Groceries") == "500"


def test_each_cell_sends_the_month_it_was_opened_in(signed_in: Client) -> None:
    make_account("Groceries", "expense")
    sent = f'?month={this_month():%Y-%m}"'

    page = signed_in.get(reverse("budget_list")).content.decode()

    assert page.count(sent) == 2


@pytest.mark.parametrize("month", ["next", "2026-13", "June"])
def test_months_after_this_one_or_unreadable_are_not_found(
    signed_in: Client, month: str
) -> None:
    asked = f"{next_month():%Y-%m}" if month == "next" else month

    response = signed_in.get(reverse("budget_list"), {"month": asked})

    assert response.status_code == 404
