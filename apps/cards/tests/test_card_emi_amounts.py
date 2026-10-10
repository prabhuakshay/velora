from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from apps.cards.statements import estimate_statement_amount
from apps.cards.tests.conftest import make_card_emi, record

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.cards.models import CardEMI

pytestmark = pytest.mark.django_db

# 100000 over 12 months at 15%: an EMI of 9025.83, the first with 1250.00
# interest and 225.00 GST (a worked reducing-balance example).
SEPTEMBER = (date(2026, 8, 16), date(2026, 9, 15))
OCTOBER = (date(2026, 9, 16), date(2026, 10, 15))


def test_the_purchase_is_left_out_and_the_installment_billed(
    card: Account, groceries: Account
) -> None:
    make_card_emi(card)
    record(card, groceries, "500", date(2026, 9, 1))

    assert estimate_statement_amount(card, *SEPTEMBER) == Decimal("9750.83")


def test_a_later_period_bills_that_months_installment(card: Account) -> None:
    make_card_emi(card)

    # 9025.83 with 1152.80 interest, plus 207.50 GST.
    assert estimate_statement_amount(card, *OCTOBER) == Decimal("9233.33")


def test_the_last_installment_clears_the_rounding(card: Account) -> None:
    make_card_emi(card)

    # 8914.41 principal and 111.43 interest, plus 20.06 GST.
    august = (date(2027, 7, 16), date(2027, 8, 15))
    assert estimate_statement_amount(card, *august) == Decimal("9045.90")


def test_nothing_is_billed_after_the_last_installment(card: Account) -> None:
    make_card_emi(card)

    september = (date(2027, 8, 16), date(2027, 9, 15))
    assert estimate_statement_amount(card, *september) == 0


def test_a_no_cost_emi_splits_the_principal_evenly(card: Account) -> None:
    make_card_emi(card, principal="30000", months=3, annual_rate="0")

    assert estimate_statement_amount(card, *SEPTEMBER) == Decimal(10000)
    assert estimate_statement_amount(card, *OCTOBER) == Decimal(10000)


def test_the_processing_fee_is_billed_with_the_first_installment(
    card: Account,
) -> None:
    make_card_emi(
        card, principal="30000", months=3, annual_rate="0", processing_fee="199"
    )

    assert estimate_statement_amount(card, *SEPTEMBER) == Decimal(10199)
    assert estimate_statement_amount(card, *OCTOBER) == Decimal(10000)


def test_a_purchase_billed_from_a_later_statement_leaves_its_own_period(
    card: Account,
) -> None:
    make_card_emi(
        card,
        principal="30000",
        months=3,
        annual_rate="0",
        first_statement=date(2026, 10, 15),
    )

    assert estimate_statement_amount(card, *SEPTEMBER) == 0
    assert estimate_statement_amount(card, *OCTOBER) == Decimal(10000)


def foreclose(emi: CardEMI, on: date, fee: str) -> None:
    emi.foreclosed_on = on
    emi.foreclosure_fee = Decimal(fee)
    emi.save()


def test_foreclosure_bills_the_remaining_principal_and_fee_next(
    card: Account,
) -> None:
    foreclose(make_card_emi(card), date(2026, 11, 1), "1000")

    # Two installments paid off 7775.83 and 7873.03 of the principal.
    november = (date(2026, 10, 16), date(2026, 11, 15))
    assert estimate_statement_amount(card, *november) == Decimal("85351.14")


def test_foreclosure_stops_later_installments(card: Account) -> None:
    foreclose(make_card_emi(card), date(2026, 11, 1), "1000")

    december = (date(2026, 11, 16), date(2026, 12, 15))
    assert estimate_statement_amount(card, *OCTOBER) == Decimal("9233.33")
    assert estimate_statement_amount(card, *december) == 0
