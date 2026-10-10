from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, list_page, make_account
from apps.accounts.tests.test_account_transactions import record, view_page
from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_net_worth import home_page
from apps.users.tests.conftest import privacy_mode_off_url, turn_on
from apps.users.tests.test_number_format import use_format
from conftest import PASSWORD

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_turning_on_redirects_to_next(signed_in: Client, user: User) -> None:
    next_url = reverse("transaction_list")

    response = signed_in.post(reverse("privacy_mode_on"), {"next": next_url})

    assert response.status_code == 302
    assert response["Location"] == next_url
    user.refresh_from_db()
    assert user.privacy_mode


def test_unsafe_next_falls_back_to_home(signed_in: Client) -> None:
    response = signed_in.post(
        reverse("privacy_mode_on"), {"next": "https://evil.example.com/"}
    )

    assert response["Location"] == reverse("index")


def test_turning_on_rejects_get(signed_in: Client, user: User) -> None:
    response = signed_in.get(reverse("privacy_mode_on"))

    assert response.status_code == 405
    user.refresh_from_db()
    assert not user.privacy_mode


def test_turning_on_adds_no_user_history(signed_in: Client, user: User) -> None:
    rows = user.history.count()

    turn_on(signed_in)

    assert user.history.count() == rows


def test_logging_in_keeps_privacy_mode(client: Client, user: User) -> None:
    turn_on_for(user)

    client.post(reverse("login"), {"username": user.email, "password": PASSWORD})

    user.refresh_from_db()
    assert user.privacy_mode


def turn_on_for(user: User) -> None:
    user.privacy_mode = True
    user.save()


MASK = '<span role="img" aria-label="Amount hidden">₹••••</span>'


def test_home_page_masks_net_worth_without_sign_or_red(signed_in: Client) -> None:
    opening("Bank", "asset", "1000")
    opening("Loan", "liability", "123456")
    turn_on(signed_in)

    page = home_page(signed_in)

    assert f"Net Worth {MASK}" in page
    assert f"Assets {MASK}" in page
    assert f"Liabilities {MASK}" in page
    assert "₹1,000.00" not in page
    assert "1,22,456.00" not in page
    assert "-₹" not in page
    assert "text-red-600" not in page


PAGES = ["index", "transaction_list", "preferences"]


@pytest.mark.parametrize("page", PAGES)
def test_eye_icon_offers_turning_on_from_every_page(
    signed_in: Client, page: str
) -> None:
    url = reverse(page)

    body = signed_in.get(url).content.decode()

    assert f'action="{reverse("privacy_mode_on")}"' in body
    assert f'name="next" value="{url}"' in body
    assert 'aria-label="Turn on Privacy Mode"' in body


@pytest.mark.parametrize("page", PAGES)
def test_eye_icon_shows_privacy_mode_is_on(signed_in: Client, page: str) -> None:
    turn_on(signed_in)

    body = signed_in.get(reverse(page)).content.decode()

    assert "Privacy Mode is on" in body
    assert reverse("privacy_mode_on") not in body


def test_home_page_replaces_chart_with_placeholder(signed_in: Client) -> None:
    opening("Bank", "asset", "1000")
    turn_on(signed_in)

    page = home_page(signed_in)

    assert "Hidden in Privacy Mode" in page
    assert "<polyline" not in page
    assert "points=" not in page


def test_account_pages_mask_balances_without_sign_or_red(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "1234.50")
    rent = make_account("Rent", "expense")
    record(date(2026, 3, 1), bank, rent, "5000", "Rent")
    turn_on(signed_in)

    for page in (list_page(signed_in, "asset"), view_page(signed_in, bank)):
        assert f"Balance {MASK}" in page
        assert f"Opening Balance {MASK}" in page
        assert "1,234.50" not in page
        assert "3,765.50" not in page
        assert "-₹" not in page
        assert '"text-sm text-red-600"' not in page
        assert "mt-2 text-sm text-red-600" not in page
    assert "5,000.00" not in view_page(signed_in, bank)


def test_transaction_list_masks_amounts(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    record(date(2026, 3, 1), bank, rent, "2500", "Rent")
    turn_on(signed_in)

    page = signed_in.get(reverse("transaction_list")).content.decode()

    assert MASK in page
    assert "2,500.00" not in page


def test_merge_page_shows_no_real_amounts(signed_in: Client) -> None:
    old_bank = opening("Old bank", "asset", "4321")
    bank = opening("Bank", "asset", "100")
    turn_on(signed_in)

    page = signed_in.get(
        account_url("account_merge", old_bank), {"target": bank.pk}
    ).content.decode()

    assert "4,321.00" not in page
    assert "100.00" not in page


def test_number_format_and_stored_values_stay_unchanged(
    signed_in: Client, user: User
) -> None:
    use_format(user, "international")
    bank = opening("Bank", "asset", "1234567")

    turn_on(signed_in)

    user.refresh_from_db()
    bank.refresh_from_db()
    assert user.number_format == "international"
    assert bank.opening_balance == Decimal(1234567)


@pytest.mark.parametrize("page", PAGES)
def test_eye_icon_leads_to_privacy_mode_off_page_while_on(
    signed_in: Client, page: str
) -> None:
    url = reverse(page)
    turn_on(signed_in)

    body = signed_in.get(url).content.decode()

    assert f'href="{privacy_mode_off_url(url)}"' in body
    assert 'aria-label="Privacy Mode is on. Turn it off"' in body


def turn_off(
    client: Client, password: str = PASSWORD, next_url: str = "/"
) -> _MonkeyPatchedWSGIResponse:
    return client.post(
        reverse("privacy_mode_off"),
        {"password": password, "next": next_url},
        REMOTE_ADDR="203.0.113.7",
    )


def test_correct_password_turns_off_and_redirects_to_next(
    signed_in: Client, user: User
) -> None:
    next_url = reverse("transaction_list")
    turn_on(signed_in)

    response = turn_off(signed_in, next_url=next_url)

    assert response.status_code == 302
    assert response["Location"] == next_url
    user.refresh_from_db()
    assert not user.privacy_mode


def test_privacy_mode_off_page_carries_next_into_the_form(signed_in: Client) -> None:
    next_url = reverse("transaction_list")
    turn_on(signed_in)

    page = signed_in.get(
        reverse("privacy_mode_off"), {"next": next_url}
    ).content.decode()

    assert 'type="password"' in page
    assert f'name="next" value="{next_url}"' in page


def test_turning_off_with_unsafe_next_falls_back_to_home(signed_in: Client) -> None:
    turn_on(signed_in)

    response = turn_off(signed_in, next_url="https://evil.example.com/")

    assert response["Location"] == reverse("index")


def test_wrong_password_keeps_privacy_mode_on(signed_in: Client, user: User) -> None:
    turn_on(signed_in)

    response = turn_off(signed_in, "wrong")

    assert response.status_code == 200
    assert "Wrong password." in response.content.decode()
    user.refresh_from_db()
    assert user.privacy_mode


def test_turning_off_adds_no_user_history(signed_in: Client, user: User) -> None:
    turn_on(signed_in)
    rows = user.history.count()

    turn_off(signed_in)

    assert user.history.count() == rows


def test_wrong_passwords_lock_out_turning_off_and_login(
    signed_in: Client, user: User
) -> None:
    turn_on(signed_in)
    for _ in range(settings.AXES_FAILURE_LIMIT):
        turn_off(signed_in, "wrong")

    turn_off_response = turn_off(signed_in)
    login_response = Client().post(
        reverse("login"),
        {"username": user.email, "password": PASSWORD},
        REMOTE_ADDR="203.0.113.7",
    )

    assert turn_off_response.status_code == 429
    assert b"Account locked" in turn_off_response.content
    user.refresh_from_db()
    assert user.privacy_mode
    assert login_response.status_code == 429


def test_transaction_edit_sends_to_privacy_mode_off_page(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    edit_url = reverse(
        "transaction_edit", args=[record(date(2026, 3, 1), bank, rent, "50", "R").pk]
    )
    turn_on(signed_in)

    response = signed_in.get(edit_url)

    assert response.status_code == 302
    assert response["Location"] == privacy_mode_off_url(edit_url)


def test_account_edit_sends_to_privacy_mode_off_page(signed_in: Client) -> None:
    edit_url = account_url("account_edit", opening("Bank", "asset", "1000"))
    turn_on(signed_in)

    response = signed_in.get(edit_url)

    assert response.status_code == 302
    assert response["Location"] == privacy_mode_off_url(edit_url)


@pytest.mark.parametrize(
    "url", [reverse("transaction_create"), reverse("account_create", args=["asset"])]
)
def test_create_pages_stay_open(signed_in: Client, url: str) -> None:
    turn_on(signed_in)

    assert signed_in.get(url).status_code == 200


def test_edit_pages_open_while_off(signed_in: Client) -> None:
    bank = opening("Bank", "asset", "0")
    rent = make_account("Rent", "expense")
    transaction = record(date(2026, 3, 1), bank, rent, "50", "R")

    for url in (
        reverse("transaction_edit", args=[transaction.pk]),
        account_url("account_edit", bank),
    ):
        assert signed_in.get(url).status_code == 200


def test_correct_password_clears_failed_attempts(signed_in: Client) -> None:
    turn_on(signed_in)
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        turn_off(signed_in, "wrong")
    turn_off(signed_in)
    turn_on(signed_in)

    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        turn_off(signed_in, "wrong")
    response = turn_off(signed_in)

    assert response.status_code == 302


def test_masked_amount_is_labelled_for_screen_readers(signed_in: Client) -> None:
    opening("Bank", "asset", "1000")
    turn_on(signed_in)

    page = home_page(signed_in)

    assert 'role="img" aria-label="Amount hidden"' in page


def test_privacy_mode_off_page_cancels_to_home(signed_in: Client) -> None:
    turn_on(signed_in)

    page = signed_in.get(
        reverse("privacy_mode_off"), {"next": reverse("transaction_list")}
    ).content.decode()

    assert f'<a href="{reverse("index")}" class="link">Cancel</a>' in page
