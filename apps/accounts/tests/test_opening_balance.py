from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Account

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db

BALANCE_KINDS = ["asset", "liability"]
FLOW_KINDS = ["expense", "income"]


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


@pytest.mark.parametrize(
    ("kind", "balance", "on"),
    [
        ("asset", None, None),
        ("liability", Decimal(1), None),
        ("expense", Decimal(1), date(2026, 1, 1)),
        ("income", None, date(2026, 1, 1)),
    ],
)
def test_opening_balance_must_match_kind(
    kind: str, balance: Decimal | None, on: date | None
) -> None:
    account = Account(
        name="X", kind=kind, opening_balance=balance, opening_balance_date=on
    )

    with pytest.raises(ValidationError):
        account.full_clean()
    with pytest.raises(IntegrityError):
        account.save()


@pytest.mark.parametrize("kind", BALANCE_KINDS)
def test_balance_form_defaults_opening_balance_to_zero_and_today(
    signed_in: Client, kind: str
) -> None:
    response = signed_in.get(reverse("account_create", kwargs={"kind": kind}))

    form = response.context["form"]
    assert form["opening_balance"].value() == 0
    assert form["opening_balance_date"].value() == timezone.localdate()
    assert b'name="opening_balance"' in response.content
    assert b'name="opening_balance_date"' in response.content


@pytest.mark.parametrize("kind", FLOW_KINDS)
def test_flow_form_has_no_opening_balance(signed_in: Client, kind: str) -> None:
    response = signed_in.get(reverse("account_create", kwargs={"kind": kind}))

    assert b"opening_balance" not in response.content


@pytest.mark.parametrize("kind", BALANCE_KINDS)
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


@pytest.mark.parametrize("kind", BALANCE_KINDS)
def test_create_without_opening_balance_is_rejected(
    signed_in: Client, kind: str
) -> None:
    response = signed_in.post(
        reverse("account_create", kwargs={"kind": kind}), {"name": "Bank"}
    )

    assert response.status_code == 200
    assert not Account.objects.exists()


@pytest.mark.parametrize("kind", FLOW_KINDS)
def test_flow_account_ignores_posted_opening_balance(
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

    assert b"-1500.75" in response.content
