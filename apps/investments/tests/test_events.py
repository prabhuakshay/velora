from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.tests.conftest import make_account
from apps.accounts.tests.test_balance import opening
from apps.investments import events
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.tests.conftest import make_direct
from apps.quick_add.models import Draft
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

IMPORT = Draft.Source.INVESTMENT_IMPORT


@pytest.fixture
def fund() -> Instrument:
    return Instrument.objects.create(
        isin="INF000000010", name="Nifty Fund", kind="mutual_fund"
    )


@pytest.fixture
def kuvera() -> Account:
    return make_direct(opening("HDFC", "asset", "50000"))


def event(account: Account, kind: str, day: int = 1, **parts: Any) -> InvestmentEvent:
    return InvestmentEvent(
        account=account,
        instrument=Instrument.objects.get(name="Nifty Fund"),
        kind=kind,
        date=date(2026, 3, day),
        **{
            name: Decimal(value) if isinstance(value, str) else value
            for name, value in parts.items()
        },
    )


def buy(account: Account, units: str = "10") -> InvestmentEvent:
    return event(account, "buy", units=units, amount="100")


def sell(account: Account) -> InvestmentEvent:
    return event(account, "sell", day=2, units="10", amount="120")


def recorded(new: InvestmentEvent) -> InvestmentEvent:
    events.record(new)
    ProcrastinateJob.objects.all().delete()
    return new


@pytest.mark.usefixtures("fund")
def test_a_sell_is_checked_against_waiting_drafts_only_as_a_draft(
    kuvera: Account,
) -> None:
    events.propose(buy(kuvera), IMPORT)

    assert events.check(sell(kuvera)) == [
        "Only 0 units of Nifty Fund were held on 2 Mar 2026."
    ]
    assert events.check(sell(kuvera), as_draft=True) == []


@pytest.mark.usefixtures("fund")
def test_an_edited_event_is_checked_in_place_of_its_recorded_self(
    kuvera: Account,
) -> None:
    bought = recorded(buy(kuvera))
    recorded(sell(kuvera))

    smaller = buy(kuvera, units="4")
    smaller.pk = bought.pk

    assert events.check(smaller) == [
        "Only 4 units of Nifty Fund were held on 2 Mar 2026."
    ]
    assert events.check(buy(kuvera, units="4")) == []


@pytest.mark.usefixtures("fund")
def test_deleting_is_refused_while_a_sell_needs_the_units(kuvera: Account) -> None:
    bought = recorded(buy(kuvera))
    sold = recorded(sell(kuvera))

    assert events.delete(bought) == (
        "Only 0 units of Nifty Fund were held on 2 Mar 2026."
    )
    assert events.delete(sold) == ""
    assert list(InvestmentEvent.objects.all()) == [bought]
    assert list(Transaction.objects.all()) == [bought.transaction]


@pytest.mark.usefixtures("fund")
def test_the_ledger_is_checked_unless_drafting(kuvera: Account) -> None:
    dividend = event(kuvera, "dividend", amount="9")

    assert events.check(dividend) == ["Split 1 From: This field is required."]
    assert events.check(dividend, as_draft=True) == []
    with pytest.raises(ValueError, match="Check the event before recording it"):
        events.record(dividend)


@pytest.mark.usefixtures("fund")
@pytest.mark.parametrize("kind", ["buy", "sell", "merger"])
def test_recording_any_event_queues_a_backfill(kuvera: Account, kind: str) -> None:
    recorded(buy(kuvera))
    merged = Instrument.objects.create(name="Merged Fund", kind="mutual_fund")
    new = {
        "buy": buy(kuvera),
        "sell": sell(kuvera),
        "merger": event(kuvera, "merger", day=3, new_instrument=merged),
    }[kind]

    events.record(new)

    assert ProcrastinateJob.objects.get().task_name == "investments.backfill_prices"


@pytest.mark.usefixtures("fund")
def test_a_dividend_reads_the_same_by_hand_and_as_a_draft(kuvera: Account) -> None:
    dividend = event(kuvera, "dividend", amount="9")
    events.record(dividend, make_account("Dividends", "income"))

    draft = events.propose(event(kuvera, "dividend", amount="9"), IMPORT)

    assert dividend.transaction is not None
    assert dividend.transaction.description == "Dividend from Nifty Fund"
    assert draft.description == "Dividend from Nifty Fund"


@pytest.mark.usefixtures("fund")
def test_a_posted_draft_records_its_event_linked_to_its_transaction(
    kuvera: Account,
) -> None:
    draft = events.propose(buy(kuvera), IMPORT)
    transaction = Transaction.objects.create(date=date(2026, 3, 1))

    assert events.draft_problems(draft) == []
    events.draft_posted(draft, transaction)

    assert InvestmentEvent.objects.get().transaction == transaction
    assert ProcrastinateJob.objects.get().task_name == "investments.backfill_prices"
