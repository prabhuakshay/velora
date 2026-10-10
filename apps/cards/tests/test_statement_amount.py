from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.cards.statements import estimate_statement_amount
from apps.cards.tests.conftest import make_card, record

if TYPE_CHECKING:
    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db

SEPTEMBER = (date(2026, 8, 16), date(2026, 9, 15))


def test_spends_in_the_period_add_up(card: Account, groceries: Account) -> None:
    record(card, groceries, "1200", date(2026, 8, 16))
    record(card, groceries, "800.50", date(2026, 9, 15))

    assert estimate_statement_amount(card, *SEPTEMBER) == Decimal("2000.50")


def test_spends_outside_the_period_are_left_out(
    card: Account, groceries: Account
) -> None:
    record(card, groceries, "1200", date(2026, 8, 15))
    record(card, groceries, "800", date(2026, 9, 16))

    assert estimate_statement_amount(card, *SEPTEMBER) == 0


def test_refunds_and_payments_to_the_card_reduce_it(
    card: Account, groceries: Account
) -> None:
    assert card.pays_from
    record(card, groceries, "5000", date(2026, 8, 20))
    record(groceries, card, "700", date(2026, 8, 25))
    record(card.pays_from, card, "1000", date(2026, 9, 1))

    assert estimate_statement_amount(card, *SEPTEMBER) == Decimal(3300)


def test_another_cards_spends_are_left_out(card: Account, groceries: Account) -> None:
    record(make_card("ICICI card"), groceries, "900", date(2026, 9, 1))

    assert estimate_statement_amount(card, *SEPTEMBER) == 0
