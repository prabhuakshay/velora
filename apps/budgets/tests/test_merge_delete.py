from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.merge import AccountMerge
from apps.accounts.tests.conftest import account_url, make_account
from apps.budgets.models import set_budget
from apps.budgets.picture import budget_picture
from apps.budgets.tests.conftest import JUNE, TODAY

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

MAY = date(2026, 5, 1)


def budgets(month: date) -> dict[str, Decimal]:
    return {row.account.name: row.budget for row in budget_picture(month).rows}


def test_merge_hands_the_source_budget_to_a_target_without_one() -> None:
    fun = make_account("Fun", "expense")
    food = make_account("Food", "expense")
    set_budget(fun, Decimal(3000), date(2026, 5, 10))
    set_budget(fun, Decimal(4000), TODAY)

    AccountMerge(source=fun, target=food).run()

    assert budgets(MAY) == {"Food": Decimal(3000)}
    assert budgets(JUNE) == {"Food": Decimal(4000)}


def test_merge_keeps_the_target_budget_and_drops_the_source_one() -> None:
    fun = make_account("Fun", "expense")
    food = make_account("Food", "expense")
    set_budget(fun, Decimal(3000), date(2026, 5, 10))
    set_budget(food, Decimal(9000), TODAY)

    AccountMerge(source=fun, target=food).run()

    assert budgets(MAY) == {}
    assert budgets(JUNE) == {"Food": Decimal(9000)}


def test_deleting_an_expense_account_deletes_its_budget(signed_in: Client) -> None:
    fun = make_account("Fun", "expense")
    food = make_account("Food", "expense")
    set_budget(fun, Decimal(3000), date(2026, 5, 10))
    set_budget(food, Decimal(9000), TODAY)

    signed_in.post(account_url("account_delete", fun))

    assert budgets(MAY) == {}
    assert budgets(JUNE) == {"Food": Decimal(9000)}
