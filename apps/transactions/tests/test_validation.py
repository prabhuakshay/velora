from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import form_data, row, split_rows

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def post(client: Client, data: dict[str, object]) -> str:
    response = client.post(reverse("transaction_create"), data)
    assert response.status_code == 200
    assert not Transaction.objects.exists()
    return response.content.decode()


@pytest.mark.parametrize("amount", ["0", "-5", "10.001"])
def test_amount_must_be_positive_with_at_most_two_decimals(
    signed_in: Client, amount: str
) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    body = post(signed_in, form_data(bank, groceries, amount))

    assert "Ensure" in body


def test_split_from_an_account_to_itself_is_rejected(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")

    body = post(signed_in, form_data(bank, bank))

    assert "A Split cannot go from an Account to itself." in body


@pytest.mark.parametrize(
    ("source", "destination", "error"),
    [
        ("asset", "income", "An Income Account can only be a source."),
        ("expense", "income", "An Income Account can only be a source."),
        ("income", "income", "An Income Account can only be a source."),
        (
            "expense",
            "expense",
            (
                "An Expense Account can only be a source in a Refund to an Asset "
                "or Liability Account."
            ),
        ),
        (
            "income",
            "expense",
            "A Split cannot go from an Income Account to an Expense Account.",
        ),
    ],
)
def test_direction_rules_reject_split(
    signed_in: Client, source: str, destination: str, error: str
) -> None:
    body = post(
        signed_in,
        form_data(make_account("From", source), make_account("To", destination)),
    )

    assert error in body


@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("asset", "asset"),
        ("asset", "liability"),
        ("liability", "asset"),
        ("liability", "liability"),
        ("income", "asset"),
        ("income", "liability"),
        ("asset", "expense"),
        ("liability", "expense"),
        ("expense", "asset"),
        ("expense", "liability"),
    ],
)
def test_direction_rules_allow_split(
    signed_in: Client, source: str, destination: str
) -> None:
    signed_in.post(
        reverse("transaction_create"),
        form_data(make_account("From", source), make_account("To", destination)),
    )

    assert Transaction.objects.count() == 1


def test_date_after_today_is_rejected(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    tomorrow = timezone.localdate() + timedelta(days=1)

    body = post(signed_in, form_data(bank, groceries, date=tomorrow.isoformat()))

    assert "The date cannot be after today." in body


@pytest.mark.parametrize("kind", ["asset", "liability"])
@pytest.mark.parametrize("side", ["from", "to"])
def test_date_before_an_opening_balance_date_is_rejected(
    signed_in: Client, kind: str, side: str
) -> None:
    account = make_account("Card", kind)
    account.opening_balance_date = date(2026, 3, 2)
    account.save()
    other = make_account("Cash" if side == "from" else "Food", "asset")
    pair = (account, other) if side == "from" else (other, account)

    body = post(signed_in, form_data(*pair, date="2026-03-01"))

    assert (
        "The date cannot be before the Opening Balance date of Card (2 Mar 2026)."
        in body
    )


def test_opening_balance_errors_show_on_each_offending_split_row(
    signed_in: Client,
) -> None:
    card, cash, loan = (
        make_account(name, kind)
        for name, kind in [("Card", "liability"), ("Cash", "asset"), ("Loan", "asset")]
    )
    for account in (card, cash):
        account.opening_balance_date = date(2026, 3, 2)
        account.save()
    food = make_account("Food", "expense")
    data = split_rows(row(loan, food), row(card, food), row(cash, food))

    body = post(signed_in, data)

    def error(name: str) -> str:
        return f"Opening Balance date of {name} (2 Mar 2026)."

    date_field, *rows = body.split("<legend")
    assert "Opening Balance" not in date_field
    assert "Opening Balance" not in rows[0]
    assert error("Card") in rows[1]
    assert error("Cash") not in rows[1]
    assert error("Cash") in rows[2]
    assert error("Card") not in rows[2]


def test_date_on_the_opening_balance_date_is_allowed(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")

    signed_in.post(
        reverse("transaction_create"), form_data(bank, groceries, date="2026-01-01")
    )

    assert Transaction.objects.count() == 1
