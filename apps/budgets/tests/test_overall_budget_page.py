from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.budgets.tests.conftest import move
from apps.budgets.tests.test_budgets_page import budgets_text, set_on
from apps.quick_add.tests.conftest import make_manual_draft
from apps.users.tests.conftest import privacy_mode_off_url, turn_on
from apps.users.tests.test_privacy_mode import MASK

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def set_overall(client: Client, amount: str) -> str:
    response = client.post(reverse("overall_budget_set"), {"amount": amount})
    if response.status_code == 302:
        assert response["Location"] == reverse("budget_list")
        return ""
    return page_text(response.content.decode())


def test_the_page_offers_to_set_an_overall_budget(signed_in: Client) -> None:
    page = signed_in.get(reverse("budget_list")).content.decode()

    assert reverse("overall_budget_set") in page
    assert "Set an Overall Budget" in page_text(page)


def test_the_overall_budget_shows_budget_spent_and_left(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")
    move(today, bank, groceries, "2500")
    move(today, bank, make_account("Fun", "expense"), "1500")

    set_overall(signed_in, "50000")

    text = budgets_text(signed_in)
    assert "Saved the Overall Budget." in text
    assert "Overall Budget Budget ₹50,000.00 · Spent ₹4,000.00" in text
    assert "₹46,000.00 left" in text
    assert "Unbudgeted ₹1,500.00" in text


def test_the_overall_budget_shows_all_that_is_expected(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    set_on(signed_in, rent, "30000")
    make_manual_draft((bank, rent, "25000"), date=today)
    make_manual_draft((bank, make_account("Fun", "expense"), "700"), date=today)

    set_overall(signed_in, "50000")

    assert "Spent ₹0.00 · Expected ₹25,700.00 ₹50,000.00 left" in budgets_text(
        signed_in
    )


def test_the_overall_budget_shows_its_state(signed_in: Client) -> None:
    today = timezone.localdate()
    set_overall(signed_in, "1000")
    move(today, opening("Bank", "asset", "0"), make_account("Fun", "expense"), "950")

    assert "Overall Budget Close" in budgets_text(signed_in)


def test_changing_the_overall_budget_replaces_it(signed_in: Client) -> None:
    set_overall(signed_in, "50000")

    set_overall(signed_in, "60000")

    text = budgets_text(signed_in)
    assert "Budget ₹60,000.00" in text
    assert "₹50,000.00" not in text


def test_the_change_form_starts_from_the_overall_budget(signed_in: Client) -> None:
    set_overall(signed_in, "50000")

    page = signed_in.get(reverse("overall_budget_set")).content.decode()

    assert 'value="50000.00"' in page
    assert reverse("overall_budget_remove") in page


def test_removing_the_overall_budget_drops_it_from_the_page(
    signed_in: Client,
) -> None:
    set_overall(signed_in, "50000")

    response = signed_in.post(reverse("overall_budget_remove"))

    assert response["Location"] == reverse("budget_list")
    text = budgets_text(signed_in)
    assert "Removed the Overall Budget from this month on." in text
    assert "₹50,000.00" not in text
    assert "Set an Overall Budget" in text


def test_a_zero_overall_budget_is_over_at_any_spent(signed_in: Client) -> None:
    set_overall(signed_in, "0")
    move(
        timezone.localdate(),
        opening("Bank", "asset", "0"),
        make_account("Fun", "expense"),
        "1",
    )

    assert "Overall Budget Over Budget ₹0.00" in budgets_text(signed_in)


def test_a_negative_overall_budget_is_refused(signed_in: Client) -> None:
    text = set_overall(signed_in, "-1")

    assert "Enter 0 or more." in text
    assert "Set an Overall Budget" in budgets_text(signed_in)


def test_budgets_adding_up_to_more_are_saved_with_a_note(signed_in: Client) -> None:
    set_overall(signed_in, "10000")

    set_on(signed_in, make_account("Rent", "expense"), "30000")

    text = budgets_text(signed_in)
    assert "Budget ₹30,000.00" in text
    assert "The Budgets add up to more than the Overall Budget." in text


def test_no_note_while_the_budgets_fit(signed_in: Client) -> None:
    set_overall(signed_in, "30000")
    set_on(signed_in, make_account("Rent", "expense"), "30000")

    assert "add up to more" not in budgets_text(signed_in)


def test_privacy_mode_masks_the_overall_budget(signed_in: Client) -> None:
    today = timezone.localdate()
    set_overall(signed_in, "12000")
    bank = opening("Bank", "asset", "0")
    fun = make_account("Fun", "expense")
    move(today, bank, fun, "13000")
    make_manual_draft((bank, fun, "14000"), date=today)
    turn_on(signed_in)

    page = signed_in.get(reverse("budget_list")).content.decode()

    text = page_text(page)
    assert f"Overall Budget Over Budget {strip_tags(MASK)}" in text
    assert f"Expected {strip_tags(MASK)}" in text
    assert f"Unbudgeted {strip_tags(MASK)}" in text
    assert "12,000" not in page
    assert "13,000" not in page
    assert "14,000" not in page
    assert "1,000" not in page
    assert "text-red-600" not in page


def test_privacy_mode_blocks_the_overall_budget_form(signed_in: Client) -> None:
    turn_on(signed_in)
    url = reverse("overall_budget_set")

    response = signed_in.get(url)

    assert response["Location"] == privacy_mode_off_url(url)


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
    set_overall(signed_in, "120000")

    text = budgets_text(signed_in)
    assert "Budget ₹120,000.00 · Spent ₹150,000.00 · Expected ₹160,000.00" in text
    assert "Unbudgeted ₹150,000.00" in text
