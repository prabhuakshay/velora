from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.budget.models import ExpenseAccount

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_expense_account(name: str) -> ExpenseAccount:
    return ExpenseAccount.objects.create(name=name)


@pytest.fixture
def signed_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_merge_removes_source_and_keeps_target(signed_in: Client) -> None:
    source = make_expense_account("Walmrt")
    target = make_expense_account("Walmart")
    url = reverse("expense_account_merge", args=[source.pk])

    page = signed_in.get(url)
    assert page.status_code == 200
    assert b"Walmart" in page.content

    response = signed_in.post(url, {"target": target.pk})

    assert response["Location"] == reverse("expense_account_list")
    assert list(ExpenseAccount.objects.all()) == [target]


def test_merge_into_itself_is_refused(signed_in: Client) -> None:
    source = make_expense_account("Walmart")

    response = signed_in.post(
        reverse("expense_account_merge", args=[source.pk]), {"target": source.pk}
    )

    assert response.status_code == 200
    assert ExpenseAccount.objects.count() == 1


def test_merge_page_offers_every_other_expense_account(signed_in: Client) -> None:
    source = make_expense_account("Walmrt")
    walmart = make_expense_account("Walmart")
    acme = make_expense_account("Acme")

    body = signed_in.get(
        reverse("expense_account_merge", args=[source.pk])
    ).content.decode()

    assert f'value="{source.pk}"' not in body
    assert f'value="{walmart.pk}"' in body
    assert f'value="{acme.pk}"' in body
