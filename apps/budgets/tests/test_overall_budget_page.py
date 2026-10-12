from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.budgets.models import Budget, set_budget
from apps.budgets.tests.conftest import cell, move, swapped
from apps.budgets.tests.test_budgets_page import (
    budgets_page,
    budgets_text,
    edit_url,
    set_on,
)
from apps.budgets.tests.test_past_months import last_month, month_url
from apps.quick_add.tests.conftest import make_manual_draft
from apps.users.tests.conftest import privacy_mode_off_url, turn_on
from apps.users.tests.test_privacy_mode import MASK

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_the_overall_budget_has_a_cell_of_its_own(signed_in: Client) -> None:
    page = budgets_page(signed_in)

    assert cell(page, "Overall Budget") == ""
    assert f'hx-post="{edit_url(None)}' in page


def test_the_overall_budget_shows_all_spent_and_expected(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    fun = make_account("Fun", "expense")
    set_on(signed_in, groceries, "12000")
    move(today, bank, groceries, "2500")
    move(today, bank, fun, "1500")
    make_manual_draft((bank, fun, "700"), date=today)

    set_on(signed_in, None, "50000")

    page = budgets_page(signed_in)
    assert cell(page, "Overall Budget") == "50000"
    text = page_text(page)
    assert "Overall Budget Spent ₹4,000.00 Expected ₹700.00 ₹46,000.00 left" in text
    assert "Unbudgeted ₹1,500.00" in text


def test_the_overall_budget_shows_its_state(signed_in: Client) -> None:
    set_on(signed_in, None, "1000")
    move(
        timezone.localdate(),
        opening("Bank", "asset", "0"),
        make_account("Fun", "expense"),
        "950",
    )

    assert "Overall Budget Spent ₹950.00 Close ₹50.00 left" in budgets_text(signed_in)


def test_typing_a_new_amount_changes_the_overall_budget(signed_in: Client) -> None:
    set_on(signed_in, None, "50000")

    set_on(signed_in, None, "60000")

    assert cell(budgets_page(signed_in), "Overall Budget") == "60000"
    assert Budget.objects.count() == 1


def test_emptying_the_cell_removes_the_overall_budget(signed_in: Client) -> None:
    set_on(signed_in, None, "50000")

    set_on(signed_in, None, "")

    page = budgets_page(signed_in)
    assert cell(page, "Overall Budget") == ""
    assert "left" not in page_text(page)


def test_a_zero_overall_budget_is_over_at_any_spent(signed_in: Client) -> None:
    set_on(signed_in, None, "0")
    move(
        timezone.localdate(),
        opening("Bank", "asset", "0"),
        make_account("Fun", "expense"),
        "1",
    )

    assert "Overall Budget Spent ₹1.00 Over -₹1.00 left" in (budgets_text(signed_in))


def test_a_negative_overall_budget_is_refused_beside_its_cell(
    signed_in: Client,
) -> None:
    response = set_on(signed_in, None, "-1")

    assert swapped(response)["overall-error"] == "Enter 0 or more."
    assert not Budget.objects.exists()


def test_saving_the_overall_budget_sends_back_what_it_changed(
    signed_in: Client,
) -> None:
    today = timezone.localdate()
    fun = make_account("Fun", "expense")
    move(today, opening("Bank", "asset", "0"), fun, "1500")
    set_budget(fun, Decimal(3000), today)

    response = set_on(signed_in, None, "2000")

    assert swapped(response) == {
        "overall-error": "",
        "overall": "Spent ₹1,500.00 ₹500.00 left",
        "unbudgeted": "₹0.00",
        "budgets-note": "The Budgets add up to more than the Overall Budget.",
    }


def test_budgets_adding_up_to_more_are_saved_with_a_note(signed_in: Client) -> None:
    set_on(signed_in, None, "10000")

    set_on(signed_in, make_account("Rent", "expense"), "30000")

    page = budgets_page(signed_in)
    assert cell(page, "Budget for Rent") == "30000"
    assert "The Budgets add up to more than the Overall Budget." in page_text(page)


def test_no_note_while_the_budgets_fit(signed_in: Client) -> None:
    set_on(signed_in, None, "30000")
    set_on(signed_in, make_account("Rent", "expense"), "30000")

    assert "add up to more" not in budgets_text(signed_in)


def test_privacy_mode_masks_the_overall_budget(signed_in: Client) -> None:
    today = timezone.localdate()
    set_on(signed_in, None, "12000")
    bank = opening("Bank", "asset", "0")
    fun = make_account("Fun", "expense")
    move(today, bank, fun, "13000")
    make_manual_draft((bank, fun, "14000"), date=today)
    turn_on(signed_in)

    page = budgets_page(signed_in)

    mask = strip_tags(MASK)
    text = page_text(page)
    assert (
        f"Overall Budget Budget {mask} Spent {mask} Expected {mask} Over {mask} left"
        in text
    )
    assert f"Unbudgeted {mask}" in text
    assert cell(page, "Overall Budget") is None
    assert "12,000" not in page
    assert "12000" not in page
    assert "13,000" not in page
    assert "14,000" not in page
    assert "1,000" not in page
    assert "text-red-600" not in page


def test_privacy_mode_refuses_an_overall_save(signed_in: Client) -> None:
    turn_on(signed_in)
    url = edit_url(None)

    response = signed_in.post(url, {"amount": "100"})

    assert response["Location"] == privacy_mode_off_url(url)
    assert not Budget.objects.exists()


def test_overall_amounts_follow_the_number_format(
    signed_in: Client, user: User
) -> None:
    user.number_format = "international"
    user.save()
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    fun = make_account("Fun", "expense")
    move(today, bank, fun, "150000")
    make_manual_draft((bank, fun, "160000"), date=today)
    set_on(signed_in, None, "120000")

    text = budgets_text(signed_in)
    assert "Spent ₹150,000.00 Expected ₹160,000.00 Over -₹30,000.00 left" in text
    assert "Unbudgeted ₹150,000.00" in text


def test_a_past_month_shows_its_overall_budget_read_only(signed_in: Client) -> None:
    set_budget(None, Decimal(40000), last_month())
    set_on(signed_in, None, "50000")

    page = signed_in.get(month_url(last_month())).content.decode()

    assert "Overall Budget Budget ₹40,000.00" in page_text(page)
    assert cell(page, "Overall Budget") is None
    assert edit_url(None) not in page


def test_a_past_month_without_an_overall_budget_shows_none(
    signed_in: Client,
) -> None:
    text = page_text(signed_in.get(month_url(last_month())).content.decode())

    assert "Overall Budget" not in text
    assert "Unbudgeted" in text
