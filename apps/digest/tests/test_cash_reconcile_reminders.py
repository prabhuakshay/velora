from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import make_account
from apps.digest.tests.test_reconcile_reminders import (
    days_ago,
    reconcile_items,
    reconciled,
    section,
)
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import make_broker, make_direct

if TYPE_CHECKING:
    from datetime import date

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def bought(broker: Account, when: date, amount: str) -> None:
    fund, _ = Instrument.objects.get_or_create(
        isin="INF000000001", defaults={"name": "Nifty Fund", "kind": "mutual_fund"}
    )
    InvestmentEvent.objects.create(
        account=broker,
        instrument=fund,
        kind="buy",
        date=when,
        units=Decimal(10),
        price=Decimal(1),
        amount=Decimal(amount),
    )


def test_a_holds_cash_account_reconciled_at_its_cash_is_not_listed() -> None:
    broker = make_broker(opening="10000")
    bought(broker, days_ago(10), "1000")
    reconciled(broker, days_ago(5), "9000")

    assert reconcile_items() == []


def test_a_holds_cash_account_off_its_cash_is_listed_with_the_difference() -> None:
    broker = make_broker(opening="10000")
    bought(broker, days_ago(10), "1000")
    reconciled(broker, days_ago(5), "9000")
    bought(broker, days_ago(6), "400")

    [item] = section().items

    assert item.label == "Zerodha: Reconciliation on 8 Oct 2026 is off by"
    assert item.amount == Decimal(400)


def test_a_direct_account_is_never_listed() -> None:
    direct = make_direct(make_account("Bank", "asset"))
    reconciled(direct, days_ago(5), "1")

    assert reconcile_items() == []
