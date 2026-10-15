from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.transactions.models import Transaction
from apps.transactions.tests.conftest import recorded, row, split_rows, transaction_url

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

DIALOG = {"HX-Request": "true"}


def test_the_list_offers_new_and_edit_in_its_dialog(signed_in: Client) -> None:
    recorded("Rent")

    body = signed_in.get(reverse("transaction_list")).content.decode()

    assert 'id="transaction-editor"' in body
    assert body.count("data-transaction-editor-open") >= 3


def test_the_dialog_gets_the_form_without_the_page(signed_in: Client) -> None:
    body = signed_in.get(reverse("transaction_create"), headers=DIALOG).content.decode()

    assert "data-transaction-editor" in body
    assert "<html" not in body
    assert "data-dialog-close" in body
    assert "data-tour-step" not in body


def test_a_boosted_visit_gets_the_whole_page(signed_in: Client) -> None:
    body = signed_in.get(
        reverse("transaction_create"), headers={**DIALOG, "HX-Boosted": "true"}
    ).content.decode()

    assert "<html" in body
    assert "data-tour-step" in body


def test_saving_in_the_dialog_sends_the_list_back(signed_in: Client) -> None:
    bank = make_account("Bank", "asset")
    food = make_account("Food", "expense")
    back = f"{reverse('transaction_list')}?q=food"

    response = signed_in.post(
        f"{reverse('transaction_create')}?next={back}",
        split_rows(row(bank, food, "250")),
        headers=DIALOG,
    )

    saved = Transaction.objects.get()
    assert response.status_code == 200
    assert response["HX-Location"] == f"{back}&selected={saved.pk}"


def test_the_list_shows_the_selected_transaction(signed_in: Client) -> None:
    older = recorded("Rent")
    recorded("Food")

    body = signed_in.get(
        f"{reverse('transaction_list')}?q=o&selected={older.pk}"
    ).content.decode()

    assert f'data-transaction-detail="{older.pk}"' in body
    row = body.split(f'data-transaction="{older.pk}"', 1)[1].split(">", 1)[0]
    assert 'aria-current="true"' in row
    # Rows and filter chips go back to the list without it.
    assert "selected%3D" not in body
    assert '<a href="?" class="inline-flex' in body


def test_an_unlisted_selection_shows_the_first(signed_in: Client) -> None:
    first = recorded("Rent")

    body = signed_in.get(
        f"{reverse('transaction_list')}?selected=999999"
    ).content.decode()

    assert f'data-transaction-detail="{first.pk}"' in body


def test_an_invalid_save_in_the_dialog_shows_the_form_again(
    signed_in: Client,
) -> None:
    transaction = recorded("Rent")

    response = signed_in.post(
        transaction_url("transaction_edit", transaction),
        split_rows(initial=0),
        headers=DIALOG,
    )

    body = response.content.decode()
    assert "HX-Location" not in response
    assert "data-transaction-editor" in body
    assert "<html" not in body
