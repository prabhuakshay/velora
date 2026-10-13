from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.models import Account
from apps.accounts.tests.conftest import make_account
from apps.cards.tests.test_card_merge import merge
from apps.goals.models import Allocation, Goal

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def goal(name: str) -> Goal:
    return Goal.objects.create(
        name=name, target_amount=Decimal(100000), target_date=date(2030, 1, 1)
    )


def allocated(
    to: Goal, account: Account, percent: str | None = None, amount: str | None = None
) -> Allocation:
    return Allocation.objects.create(
        goal=to,
        account=account,
        percent=None if percent is None else Decimal(percent),
        amount=None if amount is None else Decimal(amount),
    )


def test_merge_moves_allocations_to_the_target(signed_in: Client) -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    house = allocated(goal("House"), old_bank, percent="40")
    car = allocated(goal("Car"), old_bank, amount="5000")
    allocated(goal("Trip"), bank, percent="60")

    merge(signed_in, old_bank, bank)

    assert not Account.objects.filter(pk=old_bank.pk).exists()
    house.refresh_from_db()
    car.refresh_from_db()
    assert (house.account, car.account) == (bank, bank)


def test_merge_is_refused_when_both_are_allocated_to_one_goal(
    signed_in: Client,
) -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    house = goal("House")
    allocated(house, old_bank, percent="10")
    allocated(house, bank, amount="500")

    body = merge(signed_in, old_bank, bank)

    assert "both allocated to House" in body
    assert Account.objects.filter(pk=old_bank.pk).exists()


def test_merge_is_refused_when_percentages_would_pass_100(
    signed_in: Client,
) -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    allocated(goal("House"), old_bank, percent="50")
    allocated(goal("Car"), bank, percent="60")

    body = merge(signed_in, old_bank, bank)

    assert "110%" in body
    assert Account.objects.filter(pk=old_bank.pk).exists()
