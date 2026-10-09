from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Account

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

KINDS_WITH_BALANCE = ["asset", "liability"]
KINDS_WITHOUT_BALANCE = ["expense", "income"]


@pytest.mark.parametrize("kind", KINDS_WITH_BALANCE)
def test_balance_form_defaults_opening_balance_to_zero_and_today(
    signed_in: Client, kind: str
) -> None:
    response = signed_in.get(reverse("account_create", kwargs={"kind": kind}))

    body = response.content.decode()
    assert 'name="opening_balance" value="0"' in body
    today = timezone.localdate().isoformat()
    assert f'name="opening_balance_date" value="{today}"' in body


@pytest.mark.parametrize("kind", KINDS_WITHOUT_BALANCE)
def test_form_without_balance_has_no_opening_balance(
    signed_in: Client, kind: str
) -> None:
    response = signed_in.get(reverse("account_create", kwargs={"kind": kind}))

    assert b"opening_balance" not in response.content


@pytest.mark.parametrize("kind", KINDS_WITH_BALANCE)
def test_create_stores_negative_opening_balance_with_paise(
    signed_in: Client, kind: str
) -> None:
    signed_in.post(
        reverse("account_create", kwargs={"kind": kind}),
        {
            "name": "Card",
            "opening_balance": "-12345678901.25",
            "opening_balance_date": "2026-04-01",
        },
    )

    account = Account.objects.get()
    assert account.opening_balance == Decimal("-12345678901.25")
    assert account.opening_balance_date == date(2026, 4, 1)


@pytest.mark.parametrize("kind", KINDS_WITH_BALANCE)
@pytest.mark.parametrize(
    "posted",
    [
        {},
        {"opening_balance": "5"},
        {"opening_balance_date": "2026-04-01"},
    ],
)
def test_create_without_opening_balance_and_date_is_rejected(
    signed_in: Client, kind: str, posted: dict[str, str]
) -> None:
    response = signed_in.post(
        reverse("account_create", kwargs={"kind": kind}), {"name": "Bank", **posted}
    )

    assert response.status_code == 200
    assert not Account.objects.exists()


@pytest.mark.parametrize("kind", KINDS_WITHOUT_BALANCE)
def test_account_without_balance_ignores_posted_opening_balance(
    signed_in: Client, kind: str
) -> None:
    signed_in.post(
        reverse("account_create", kwargs={"kind": kind}),
        {"name": "Rent", "opening_balance": "5", "opening_balance_date": "2026-04-01"},
    )

    account = Account.objects.get()
    assert (account.opening_balance, account.opening_balance_date) == (None, None)


def test_edit_changes_opening_balance_and_date(signed_in: Client) -> None:
    account = Account.objects.create(
        name="Bank",
        kind="asset",
        opening_balance=Decimal(100),
        opening_balance_date=date(2026, 1, 1),
    )

    signed_in.post(
        reverse("account_edit", kwargs={"kind": "asset", "pk": account.pk}),
        {
            "name": "Bank",
            "opening_balance": "250.50",
            "opening_balance_date": "2026-02-01",
        },
    )

    account.refresh_from_db()
    assert account.opening_balance == Decimal("250.50")
    assert account.opening_balance_date == date(2026, 2, 1)


def test_list_shows_opening_balance(signed_in: Client) -> None:
    Account.objects.create(
        name="Card",
        kind="liability",
        opening_balance=Decimal("-1500.75"),
        opening_balance_date=date(2026, 1, 1),
    )

    response = signed_in.get(reverse("account_list", kwargs={"kind": "liability"}))

    assert "Opening Balance -₹1,500.75" in response.content.decode()
