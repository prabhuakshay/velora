import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import (
    KINDS,
    account_url,
    list_page,
    list_url,
    make_account,
)
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def target_choices(body: str) -> list[str]:
    match = re.search(r'<select name="target".*?</select>', body, re.DOTALL)
    assert match
    return re.findall(r'<option value="\d+">([^<]+)</option>', match.group())


def make_transaction(*splits: tuple[Account, Account, str]) -> Transaction:
    transaction = Transaction.objects.create(date=date(2026, 3, 1))
    for source, destination, amount in splits:
        transaction.splits.create(
            from_account=source, to_account=destination, amount=Decimal(amount)
        )
    return transaction


@pytest.fixture
def merge_scenario() -> tuple[Account, Account, Account]:
    """Old bank merges into Bank: two Splits move, two become self-Splits."""
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    groceries = make_account("Groceries", "expense")
    make_transaction((old_bank, groceries, "100"))
    make_transaction((old_bank, bank, "50"))
    make_transaction((bank, old_bank, "20"), (old_bank, groceries, "30"))
    return old_bank, bank, groceries


@pytest.mark.parametrize("kind", KINDS)
def test_every_account_row_offers_merge(signed_in: Client, kind: str) -> None:
    account = make_account("Old card", kind)

    assert account_url("account_merge", account) in list_page(signed_in, kind)


def test_merge_targets_are_other_accounts_of_the_same_kind(signed_in: Client) -> None:
    source = make_account("Old bank", "asset")
    make_account("Bank", "asset")
    make_account("Card", "liability")

    body = signed_in.get(account_url("account_merge", source)).content.decode()

    assert target_choices(body) == ["Bank"]


def test_confirmation_shows_what_the_merge_into_the_chosen_target_does(
    signed_in: Client, merge_scenario: tuple[Account, Account, Account]
) -> None:
    old_bank, bank, _ = merge_scenario
    url = account_url("account_merge", old_bank)

    body = signed_in.get(url, {"target": bank.pk}).content.decode()

    assert "2 Splits move to Bank." in body
    assert "2 Splits between Old bank and Bank are removed." in body
    assert "1 Transaction left with no Splits is removed." in body
    assert f'<input type="hidden" name="target" value="{bank.pk}">' in body


def test_merge_repoints_splits_and_removes_self_splits_and_the_source(
    signed_in: Client, merge_scenario: tuple[Account, Account, Account]
) -> None:
    old_bank, bank, groceries = merge_scenario

    response = signed_in.post(
        account_url("account_merge", old_bank), {"target": bank.pk}, follow=True
    )

    assert response.redirect_chain == [(list_url("asset"), 302)]
    assert "Merged Old bank into Bank." in response.content.decode()
    assert not Account.objects.filter(pk=old_bank.pk).exists()
    splits = [
        [(s.from_account, s.to_account, s.amount) for s in t.splits.all()]
        for t in Transaction.objects.order_by("pk")
    ]
    assert splits == [
        [(bank, groceries, Decimal(100))],
        [(bank, groceries, Decimal(30))],
    ]


def test_merge_adds_opening_balances_with_the_earlier_date(signed_in: Client) -> None:
    old_card = Account.objects.create(
        name="Old card",
        kind="liability",
        opening_balance=Decimal("250.50"),
        opening_balance_date=date(2025, 6, 1),
    )
    card = Account.objects.create(
        name="Card",
        kind="liability",
        opening_balance=Decimal(1000),
        opening_balance_date=date(2026, 1, 1),
    )

    signed_in.post(account_url("account_merge", old_card), {"target": card.pk})

    card.refresh_from_db()
    assert card.opening_balance == Decimal("1250.50")
    assert card.opening_balance_date == date(2025, 6, 1)


def test_change_history_records_the_merge(
    signed_in: Client, merge_scenario: tuple[Account, Account, Account]
) -> None:
    old_bank, bank, _ = merge_scenario

    signed_in.post(account_url("account_merge", old_bank), {"target": bank.pk})

    reason = "Merged Old bank into Bank"
    assert (
        Account.history.get(id=old_bank.pk, history_type="-").history_change_reason
        == reason
    )
    split_changes = Split.history.filter(history_change_reason=reason)
    assert sorted(split_changes.values_list("history_type", flat=True)) == [
        "-",
        "-",
        "~",
        "~",
    ]
    assert (
        Transaction.history.filter(
            history_change_reason=reason, history_type="-"
        ).count()
        == 1
    )


@pytest.mark.parametrize("method", ["get", "post"])
def test_merge_url_with_another_kind_is_not_found(
    signed_in: Client, method: str
) -> None:
    account = make_account("Old bank", "asset")
    url = reverse("account_merge", kwargs={"kind": "liability", "pk": account.pk})

    assert getattr(signed_in, method)(url).status_code == 404


def test_merge_requires_login(client: Client) -> None:
    account = make_account("Old bank", "asset")
    url = account_url("account_merge", account)

    assert client.get(url)["Location"].startswith(reverse("login"))


def test_target_of_another_kind_is_rejected(signed_in: Client) -> None:
    old_bank = make_account("Old bank", "asset")
    card = make_account("Card", "liability")
    url = account_url("account_merge", old_bank)

    for response in [
        signed_in.get(url, {"target": card.pk}),
        signed_in.post(url, {"target": card.pk}),
    ]:
        assert "Select a valid choice." in response.content.decode()
    assert Account.objects.count() == 2


def test_merge_works_with_the_longest_names(signed_in: Client) -> None:
    source = make_account("a" * 100, "asset")
    target = make_account("b" * 100, "asset")
    groceries = make_account("Groceries", "expense")
    transaction = Transaction.objects.create(date=date(2026, 3, 1))
    split = transaction.splits.create(
        from_account=source, to_account=groceries, amount=Decimal(5)
    )

    signed_in.post(account_url("account_merge", source), {"target": target.pk})

    assert not Account.objects.filter(pk=source.pk).exists()
    split.refresh_from_db()
    assert split.from_account == target
