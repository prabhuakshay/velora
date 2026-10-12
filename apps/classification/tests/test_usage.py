from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import make_account
from apps.classification.activity import activity, party_shares
from apps.classification.models import Party, Tag
from apps.classification.tests.conftest import move
from apps.transactions.models import Split

if TYPE_CHECKING:
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

TODAY = date(2026, 3, 15)
ZERO = Decimal(0)

type Accounts = dict[str, Account]


@pytest.fixture
def accounts() -> Accounts:
    return {
        name: make_account(name.title(), kind)
        for name, kind in [
            ("bank", "asset"),
            ("card", "liability"),
            ("food", "expense"),
            ("travel", "expense"),
            ("salary", "income"),
        ]
    }


def test_party_usage_counts_all_time_and_sums_since(accounts: Accounts) -> None:
    shop = Party.objects.create(name="Shop")
    Party.objects.create(name="Unused")
    move(date(2025, 1, 5), accounts["bank"], accounts["food"], "100", party=shop)
    move(date(2026, 3, 1), accounts["card"], accounts["food"], "40", party=shop)
    # A Refund takes back what was spent.
    move(date(2026, 3, 2), accounts["food"], accounts["card"], "15", party=shop)

    parties = {p.name: p for p in Party.objects.with_usage(date(2026, 1, 1))}

    assert (parties["Shop"].transaction_count, parties["Shop"].last_used) == (
        3,
        date(2026, 3, 2),
    )
    assert (parties["Shop"].spent, parties["Shop"].earned) == (Decimal(25), ZERO)
    assert (parties["Unused"].transaction_count, parties["Unused"].spent) == (0, ZERO)


def test_party_usage_sums_earnings(accounts: Accounts) -> None:
    employer = Party.objects.create(name="Employer")
    move(date(2026, 3, 1), accounts["salary"], accounts["bank"], "900", party=employer)

    party = Party.objects.with_usage().get()

    assert (party.spent, party.earned) == (ZERO, Decimal(900))


def test_tag_usage_counts_splits_and_leaves_out_transfers(accounts: Accounts) -> None:
    trip = Tag.objects.create(name="Trip")
    move(date(2026, 3, 1), accounts["bank"], accounts["travel"], "300", tags=[trip])
    move(date(2026, 3, 2), accounts["bank"], accounts["card"], "500", tags=[trip])

    tag = Tag.objects.with_usage().get()

    assert (tag.split_count, tag.last_used) == (2, date(2026, 3, 2))
    assert (tag.spent, tag.earned) == (Decimal(300), ZERO)


def test_activity_measures_the_main_way_by_month_and_account(
    accounts: Accounts,
) -> None:
    trip = Tag.objects.create(name="Trip")
    move(date(2025, 2, 10), accounts["bank"], accounts["travel"], "999", tags=[trip])
    move(date(2026, 2, 10), accounts["bank"], accounts["travel"], "300", tags=[trip])
    move(date(2026, 3, 1), accounts["card"], accounts["food"], "100", tags=[trip])
    move(date(2026, 3, 2), accounts["salary"], accounts["bank"], "50", tags=[trip])

    result = activity(Split.objects.filter(tags=trip), TODAY)

    assert (result.earns, result.total, result.other) == (
        False,
        Decimal(1399),
        Decimal(50),
    )
    assert (result.first, result.last) == (date(2025, 2, 10), date(2026, 3, 2))
    assert result.months[0] == (date(2025, 4, 1), ZERO)
    assert (result.this_month, result.last_month) == (Decimal(100), Decimal(300))
    assert (result.year, result.average) == (Decimal(400), Decimal(400) / 12)
    assert [(s.name, s.total, s.percent) for s in result.accounts] == [
        ("Travel", Decimal(1299), 93),
        ("Food", Decimal(100), 7),
    ]


def test_activity_of_nothing_is_all_zero() -> None:
    result = activity(Split.objects.none(), TODAY)

    assert (result.earns, result.total, result.first, result.year) == (
        False,
        ZERO,
        None,
        ZERO,
    )
    assert len(result.months) == 12
    assert result.accounts == []


def test_activity_measures_earnings_when_they_lead(accounts: Accounts) -> None:
    employer = Party.objects.create(name="Employer")
    move(date(2026, 3, 1), accounts["salary"], accounts["bank"], "900", party=employer)
    move(date(2026, 3, 2), accounts["bank"], accounts["food"], "100", party=employer)

    result = activity(Split.objects.filter(transaction__party=employer), TODAY)

    assert (result.earns, result.total, result.other) == (
        True,
        Decimal(900),
        Decimal(100),
    )
    assert [s.name for s in result.accounts] == ["Salary"]


def test_party_shares_rank_parties_by_spending(accounts: Accounts) -> None:
    trip = Tag.objects.create(name="Trip")
    hotel, cafe = Party.objects.create(name="Hotel"), Party.objects.create(name="Cafe")
    move(TODAY, accounts["bank"], accounts["travel"], "300", party=hotel, tags=[trip])
    move(TODAY, accounts["bank"], accounts["food"], "100", party=cafe, tags=[trip])
    move(TODAY, accounts["bank"], accounts["food"], "50", tags=[trip])

    shares = party_shares(Split.objects.filter(tags=trip), earns=False)

    assert [(s.name, s.percent) for s in shares] == [("Hotel", 75), ("Cafe", 25)]
