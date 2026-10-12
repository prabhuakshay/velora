from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from apps.accounts.tests.conftest import make_account
from apps.quick_add.tests.conftest import make_manual_draft

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def page_text(signed_in: Client, query: str = "") -> str:
    response = signed_in.get(reverse("forecast") + query)
    return " ".join(strip_tags(response.content.decode()).split())


def bank(opening: str = "1250000", threshold: str = "0") -> Account:
    account = make_account("Bank", "asset")
    account.opening_balance = Decimal(opening)
    account.low_balance_threshold = Decimal(threshold)
    account.save()
    return account


def dentist_in_three_days(source: Account, amount: str | None) -> None:
    dentist_in(3, source, amount)


def dentist_in(days: int, source: Account, amount: str | None = "300000") -> None:
    make_manual_draft(
        (source, make_account("Dentist", "expense"), amount),
        description="Dentist",
        date=timezone.localdate() + timedelta(days=days),
    )


def test_the_forecast_shows_each_day_and_low_balance_warnings(
    signed_in: Client,
) -> None:
    savings = bank(threshold="1000000")
    dentist_in_three_days(savings, "300000")
    when = timezone.localdate() + timedelta(days=3)

    text = page_text(signed_in)

    assert f"{when:%-d %b %Y}" in text
    assert "₹12,50,000.00" in text
    assert "₹9,50,000.00" in text
    assert f"Bank is expected under ₹10,00,000.00 from {when:%-d %b %Y}" in text


def test_an_amountless_draft_shows_as_unknown_on_its_date(signed_in: Client) -> None:
    dentist_in_three_days(bank(), None)

    text = page_text(signed_in)

    assert "Dentist ₹?" in text


def test_the_forecast_follows_the_number_format(signed_in: Client, user: User) -> None:
    bank()
    user.number_format = "international"
    user.save()

    text = page_text(signed_in)

    assert "₹1,250,000.00" in text


def test_privacy_mode_hides_every_balance(signed_in: Client, user: User) -> None:
    savings = bank(threshold="1000000")
    dentist_in_three_days(savings, "300000")
    user.privacy_mode = True
    user.save()

    text = page_text(signed_in)

    assert "Bank is expected under ₹•••• from" in text
    assert "50,000" not in text
    assert "00,000" not in text


def test_a_card_warns_it_is_expected_to_owe_over_its_limit(
    signed_in: Client,
) -> None:
    card = make_account("Card", "liability")
    card.low_balance_threshold = Decimal(50000)
    card.save()
    dentist_in_three_days(card, "60000")
    when = timezone.localdate() + timedelta(days=3)

    text = page_text(signed_in)

    assert f"Card is expected to owe over ₹50,000.00 from {when:%-d %b %Y}" in text


def test_the_timeline_lists_what_moves_the_balance_and_where(
    signed_in: Client,
) -> None:
    dentist_in_three_days(bank(), "300000")

    text = page_text(signed_in)

    assert "₹12,50,000.00 ₹9,50,000.00" in text
    assert "Dentist -₹3,00,000.00 Bank → Dentist" in text
    assert "Money in ₹0.00 Out ₹3,00,000.00" in text


def test_a_longer_horizon_reaches_further(signed_in: Client) -> None:
    dentist_in(60, bank())

    assert "Dentist" not in page_text(signed_in)
    assert "Dentist" in page_text(signed_in, "?days=90")
    assert "Dentist" not in page_text(signed_in, "?days=45")


def test_choosing_an_account_follows_only_its_moves(signed_in: Client) -> None:
    savings = bank()
    card = make_account("Card", "liability")
    dentist_in(3, card, "5000")
    make_manual_draft(
        (savings, make_account("Gym", "expense"), "7000"),
        date=timezone.localdate() + timedelta(days=4),
    )

    text = page_text(signed_in, f"?account={card.pk}")

    assert "Card · what you owe" in text
    assert "₹5,000.00 Card → Dentist" in text
    assert "Bank → Gym" not in text
    assert "Charged ₹5,000.00 Paid off ₹0.00" in text


def test_an_overdue_draft_lands_on_today(signed_in: Client) -> None:
    dentist_in(-2, bank())
    since = timezone.localdate() - timedelta(days=2)

    text = page_text(signed_in)

    assert f"Overdue since {since:%-d %b}" in text
    assert "· Today" in text


def test_an_amountless_draft_asks_for_its_amount(signed_in: Client) -> None:
    dentist_in_three_days(bank(), None)

    text = page_text(signed_in)

    assert "Amount unknown 1 Left out of the totals" in text
    assert "Dentist ₹? Set its amount" in text


def test_with_nothing_expected_the_timeline_says_so(signed_in: Client) -> None:
    bank()

    assert "Nothing expected in the next 30 days" in page_text(signed_in)


def test_without_accounts_it_offers_to_add_one(signed_in: Client) -> None:
    assert "No Asset or Liability Accounts to forecast yet" in page_text(signed_in)


def test_privacy_mode_hides_the_chart(signed_in: Client, user: User) -> None:
    bank()
    user.privacy_mode = True
    user.save()

    assert "Hidden in Privacy Mode" in page_text(signed_in)
