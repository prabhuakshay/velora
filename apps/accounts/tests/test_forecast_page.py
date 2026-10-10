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


def page_text(signed_in: Client) -> str:
    response = signed_in.get(reverse("forecast"))
    return " ".join(strip_tags(response.content.decode()).split())


def bank(opening: str = "1250000", threshold: str = "0") -> Account:
    account = make_account("Bank", "asset")
    account.opening_balance = Decimal(opening)
    account.low_balance_threshold = Decimal(threshold)
    account.save()
    return account


def dentist_in_three_days(source: Account, amount: str | None) -> None:
    make_manual_draft(
        (source, make_account("Dentist", "expense"), amount),
        description="Dentist",
        date=timezone.localdate() + timedelta(days=3),
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
