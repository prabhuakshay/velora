from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import pytest
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, strip_tags

from apps.accounts.activity import month_end
from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.budgets.models import Budget, set_budget
from apps.budgets.tests.conftest import cell, move, swapped
from apps.quick_add.tests.conftest import make_manual_draft
from apps.users.tests.conftest import privacy_mode_off_url, turn_on
from apps.users.tests.test_privacy_mode import MASK

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def budgets_page(client: Client) -> str:
    return client.get(reverse("budget_list")).content.decode()


def budgets_text(client: Client) -> str:
    return page_text(budgets_page(client))


def edit_url(account: Account | None) -> str:
    if account is None:
        return reverse("overall_budget_edit")
    return reverse("budget_edit", args=[account.pk])


def set_on(client: Client, account: Account | None, amount: str) -> Response:
    """Type the amount into the Account's Budget cell, or the Overall one's."""
    return client.post(
        edit_url(account), {"amount": amount}, headers={"HX-Request": "true"}
    )


def test_the_budgets_page_is_in_the_navigation(signed_in: Client) -> None:
    page = signed_in.get(reverse("index")).content.decode()

    assert f'href="{reverse("budget_list")}"' in page


def test_every_visible_expense_account_has_a_budget_cell(signed_in: Client) -> None:
    today = timezone.localdate()
    groceries = make_account("Groceries", "expense")
    make_account("Fuel", "expense")
    make_account("Old", "expense", hidden=True)
    gym = make_account("Gym", "expense", hidden=True)
    make_account("Salary", "income")
    set_budget(groceries, Decimal(12000), today)
    set_budget(gym, Decimal(500), today)

    page = budgets_page(signed_in)

    assert cell(page, "Budget for Groceries") == "12000"
    assert cell(page, "Budget for Fuel") == ""
    assert cell(page, "Budget for Gym") == "500"
    assert cell(page, "Budget for Old") is None
    assert cell(page, "Budget for Salary") is None


def test_each_budget_shows_spent_expected_and_left(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    move(today, bank, groceries, "2500")
    make_manual_draft((bank, groceries, "400"), date=today)
    set_budget(groceries, Decimal(12000), today)

    text = budgets_text(signed_in)

    assert "Groceries Spent ₹2,500.00 Expected ₹400.00 ₹9,500.00 left" in text


def test_an_account_without_a_budget_shows_its_spent_and_expected(
    signed_in: Client,
) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    fuel = make_account("Fuel", "expense")
    move(today, bank, fuel, "300")
    make_manual_draft((bank, fuel, "700"), date=today)

    text = budgets_text(signed_in)

    assert "Fuel Spent ₹300.00 Expected ₹700.00" in text
    assert "left" not in text


def test_each_row_links_to_the_months_transactions(signed_in: Client) -> None:
    today = timezone.localdate()
    groceries = make_account("Groceries", "expense")
    start = today.replace(day=1)
    query = urlencode(
        {"account": groceries.pk, "start": start, "end": month_end(start)}
    )

    page = budgets_page(signed_in)

    assert escape(f"{reverse('transaction_list')}?{query}") in page


def test_each_cell_saves_to_its_own_account_as_it_changes(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    page = budgets_page(signed_in)

    assert f'hx-post="{edit_url(groceries)}' in page
    assert 'hx-trigger="change"' in page


def test_typing_an_amount_sets_the_budget(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    response = set_on(signed_in, groceries, "12000")

    assert response.status_code == 200
    assert cell(budgets_page(signed_in), "Budget for Groceries") == "12000"


def test_typing_a_new_amount_changes_the_budget(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")

    set_on(signed_in, groceries, "15000")

    assert cell(budgets_page(signed_in), "Budget for Groceries") == "15000"
    assert Budget.objects.count() == 1


def test_emptying_a_cell_removes_the_budget(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    move(timezone.localdate(), opening("Bank", "asset", "0"), groceries, "2500")
    set_on(signed_in, groceries, "12000")

    set_on(signed_in, groceries, "")

    page = budgets_page(signed_in)
    assert cell(page, "Budget for Groceries") == ""
    assert "left" not in page_text(page)
    assert "Unbudgeted ₹2,500.00" in page_text(page)


def test_a_zero_budget_is_over_at_any_spent(signed_in: Client) -> None:
    takeaway = make_account("Takeaway", "expense")
    set_on(signed_in, takeaway, "0")
    move(timezone.localdate(), opening("Bank", "asset", "0"), takeaway, "1")

    page = budgets_page(signed_in)

    assert cell(page, "Budget for Takeaway") == "0"
    assert "Takeaway Spent ₹1.00 Over -₹1.00 left" in page_text(page)


def test_a_budget_close_to_its_limit_is_marked_close(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "1000")
    move(timezone.localdate(), opening("Bank", "asset", "0"), groceries, "950")

    assert "Close ₹50.00 left" in budgets_text(signed_in)


@pytest.mark.parametrize(
    ("amount", "error"), [("-1", "Enter 0 or more."), ("lots", "Enter a number.")]
)
def test_an_amount_that_is_not_a_budget_is_refused_beside_its_cell(
    signed_in: Client, amount: str, error: str
) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")

    response = set_on(signed_in, groceries, amount)

    assert swapped(response)[f"budget-{groceries.pk}-error"] == error
    assert cell(budgets_page(signed_in), "Budget for Groceries") == "12000"


def test_a_good_amount_clears_the_error(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "-1")

    response = set_on(signed_in, groceries, "100")

    assert swapped(response)[f"budget-{groceries.pk}-error"] == ""


def test_a_save_sends_back_everything_it_changed(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    groceries = make_account("Groceries", "expense")
    move(today, bank, groceries, "2500")
    move(today, bank, make_account("Fun", "expense"), "1500")
    set_budget(None, Decimal(10000), today)

    response = set_on(signed_in, groceries, "12000")

    assert swapped(response) == {
        f"budget-{groceries.pk}": "Spent ₹2,500.00 ₹9,500.00 left",
        f"budget-{groceries.pk}-error": "",
        "overall": "Spent ₹4,000.00 ₹6,000.00 left",
        "unbudgeted": "₹1,500.00",
        "budgets-note": "The Budgets add up to more than the Overall Budget.",
    }


def test_removing_a_budget_sends_back_a_row_without_one(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    move(timezone.localdate(), opening("Bank", "asset", "0"), groceries, "2500")
    set_on(signed_in, groceries, "12000")

    parts = swapped(set_on(signed_in, groceries, ""))

    assert parts[f"budget-{groceries.pk}"] == "Spent ₹2,500.00"
    assert parts["unbudgeted"] == "₹2,500.00"


@pytest.mark.parametrize("kind", ["asset", "liability", "income"])
def test_only_expense_accounts_take_a_budget(signed_in: Client, kind: str) -> None:
    other = make_account("Elsewhere", kind)

    response = set_on(signed_in, other, "100")

    assert response.status_code == 404
    assert not Budget.objects.exists()


def test_only_a_post_saves(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    response = signed_in.get(edit_url(groceries), {"amount": "100"})

    assert response.status_code == 405
    assert not Budget.objects.exists()


def test_the_database_refuses_a_negative_budget() -> None:
    groceries = make_account("Groceries", "expense")

    with pytest.raises(IntegrityError, match="budgets_budget_amount_not_negative"):
        set_budget(groceries, Decimal(-1), timezone.localdate())


def test_amounts_follow_the_number_format(signed_in: Client, user: User) -> None:
    user.number_format = "international"
    user.save()
    rent = make_account("Rent", "expense")
    move(timezone.localdate(), opening("Bank", "asset", "0"), rent, "150000")

    set_on(signed_in, rent, "120000")

    assert "Rent Spent ₹150,000.00" in budgets_text(signed_in)


def test_privacy_mode_masks_every_amount_and_locks_the_cells(
    signed_in: Client,
) -> None:
    groceries = make_account("Groceries", "expense")
    set_on(signed_in, groceries, "12000")
    move(timezone.localdate(), opening("Bank", "asset", "0"), groceries, "13000")
    turn_on(signed_in)

    page = budgets_page(signed_in)

    mask = strip_tags(MASK)
    assert (
        f"Groceries Budget {mask} Spent {mask} Expected {mask} Over {mask} left"
        in page_text(page)
    )
    assert cell(page, "Budget for Groceries") is None
    assert cell(page, "Overall Budget") is None
    assert "12,000" not in page
    assert "12000" not in page
    assert "13,000" not in page
    assert "1,000" not in page
    assert "text-red-600" not in page


def test_privacy_mode_refuses_a_save(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    turn_on(signed_in)
    url = edit_url(groceries)

    response = signed_in.post(url, {"amount": "100"})

    assert response["Location"] == privacy_mode_off_url(url)
    assert not Budget.objects.exists()


def test_change_history_records_budget_changes(superuser: User) -> None:
    client = Client()
    client.force_login(superuser)
    groceries = make_account("Groceries", "expense")
    set_on(client, groceries, "12000")
    set_on(client, groceries, "15000")
    budget = Budget.objects.get()

    page = client.get(reverse("admin:budgets_budget_history", args=[budget.pk]))

    text = page_text(page.content.decode())
    assert text.count(superuser.email) >= 2


def test_a_cell_shows_paise_only_when_there_are_some(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")

    set_on(signed_in, groceries, "1250.5")

    assert cell(budgets_page(signed_in), "Budget for Groceries") == "1250.50"


def test_budgets_needing_attention_come_first(signed_in: Client) -> None:
    today = timezone.localdate()
    bank = opening("Bank", "asset", "0")
    for name, budget, spent in [
        ("Books", 1000, 100),
        ("Fuel", 1000, 950),
        ("Groceries", 1000, 1200),
        ("Rent", 1000, 920),
    ]:
        account = make_account(name, "expense")
        set_budget(account, Decimal(budget), today)
        move(today, bank, account, str(spent))

    text = budgets_text(signed_in)

    order = sorted(["Books", "Fuel", "Groceries", "Rent"], key=text.index)
    assert order == ["Groceries", "Fuel", "Rent", "Books"]


def test_accounts_without_a_budget_wait_under_add_a_budget(signed_in: Client) -> None:
    set_budget(make_account("Rent", "expense"), Decimal(1000), timezone.localdate())
    make_account("Books", "expense")

    page = budgets_page(signed_in)

    text = page_text(page)
    assert text.index("Rent") < text.index("Add a Budget") < text.index("Books")
    assert cell(page, "Budget for Books") == ""
    assert "<details" in page
