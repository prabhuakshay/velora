from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.tests.conftest import make_account, page_text
from apps.accounts.tests.test_balance import opening
from apps.budgets.models import set_budget
from apps.budgets.tests.conftest import move
from apps.users.tests.conftest import turn_on
from apps.users.tests.test_privacy_mode import MASK

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def card(client: Client) -> str:
    """The Budgets card's HTML, or "" when the home page has none."""
    page = client.get(reverse("index")).content.decode()
    start = page.find('aria-labelledby="budgets-title"')
    if start == -1:
        return ""
    return page[start : page.index("</section>", start)]


def budget(name: str, amount: str, spent: str) -> None:
    today = timezone.localdate()
    account = make_account(name, "expense")
    set_budget(account, Decimal(amount), today)
    if spent != "0":
        move(today, opening(f"Bank for {name}", "asset", "0"), account, spent)


def test_overall_budget_comes_first_then_over_close_and_by_share(
    signed_in: Client,
) -> None:
    budget("Books", "1000", "100")
    budget("Fuel", "1000", "500")
    budget("Groceries", "1000", "950")
    budget("Rent", "1000", "1200")
    set_budget(None, Decimal(10000), timezone.localdate())

    text = page_text(card(signed_in))

    names = ["Overall Budget", "Rent", "Groceries", "Fuel", "Books"]
    places = [text.index(name) for name in names]
    assert places == sorted(places)
    assert "Over" in text.split("Rent")[1].split("Groceries")[0]
    assert "Close" in text.split("Groceries")[1].split("Fuel")[0]


def test_a_zero_budget_spent_on_comes_before_other_over_budgets(
    signed_in: Client,
) -> None:
    budget("Rent", "1000", "3000")
    budget("Gifts", "0", "10")

    text = page_text(card(signed_in))

    assert text.index("Gifts") < text.index("Rent")


def test_card_is_hidden_when_no_budget_applies_this_month(signed_in: Client) -> None:
    groceries = make_account("Groceries", "expense")
    set_budget(groceries, None, timezone.localdate())

    assert card(signed_in) == ""


def test_card_shows_an_overall_budget_alone(signed_in: Client) -> None:
    set_budget(None, Decimal(5000), timezone.localdate())

    assert "Overall Budget" in page_text(card(signed_in))


def test_amounts_follow_the_number_format(signed_in: Client, user: User) -> None:
    budget("Rent", "120000", "130000")
    user.number_format = "international"
    user.save()

    text = page_text(card(signed_in))

    assert "Spent ₹130,000.00 of ₹120,000.00" in text
    assert "-₹10,000.00 left" in text


def test_privacy_mode_masks_every_amount(signed_in: Client) -> None:
    budget("Rent", "120000", "130000")
    set_budget(None, Decimal(200000), timezone.localdate())
    turn_on(signed_in)

    html = card(signed_in)

    assert MASK in html
    assert f"Spent {strip_tags(MASK)} of {strip_tags(MASK)}" in page_text(html)
    assert "1,20,000" not in html
    assert "1,30,000" not in html
    assert "2,00,000" not in html
    assert "-₹" not in html
    assert "text-red-600" not in html


def test_budgets_past_five_fold_into_a_more_row_linking_to_the_budgets_page(
    signed_in: Client,
) -> None:
    for share, name in enumerate("ABCDEFG", start=1):
        budget(f"Account {name}", "100", str(share))

    html = card(signed_in)
    text = page_text(html)

    assert "Account G" in text
    assert "Account C" in text
    assert "Account B" not in text
    assert "2 more" in text
    assert f'href="{reverse("budget_list")}"' in html
