from datetime import date
from decimal import Decimal

import pytest

from apps.investments.replay import replay
from apps.investments.tests.test_replay import FUND, NEW_FUND, Event
from apps.investments.xirr import returns, xirr


def flow(day: str, amount: str) -> tuple[date, Decimal]:
    return date.fromisoformat(day), Decimal(amount)


def test_one_buy_grown_ten_percent_in_a_year_is_ten_percent() -> None:
    result = xirr([flow("2025-01-01", "-1000"), flow("2026-01-01", "1100")])

    assert result == pytest.approx(Decimal(10), abs=Decimal("0.0001"))


def test_matches_the_known_spreadsheet_example() -> None:
    result = xirr(
        [
            flow("2008-01-01", "-10000"),
            flow("2008-03-01", "2750"),
            flow("2008-10-30", "4250"),
            flow("2009-02-15", "3250"),
            flow("2009-04-01", "2750"),
        ]
    )

    assert result == pytest.approx(Decimal("37.336253"), abs=Decimal("0.0001"))


def test_a_loss_is_negative() -> None:
    result = xirr([flow("2025-01-01", "-1000"), flow("2026-01-01", "900")])

    assert result == pytest.approx(Decimal(-10), abs=Decimal("0.0001"))


def test_breaking_even_is_zero() -> None:
    result = xirr([flow("2025-01-01", "-1000"), flow("2025-06-01", "1000")])

    assert result == pytest.approx(Decimal(0), abs=Decimal("0.0001"))


@pytest.mark.parametrize(
    "flows",
    [
        pytest.param([], id="nothing"),
        pytest.param([flow("2025-01-01", "-1000")], id="one flow"),
        pytest.param(
            [flow("2025-01-01", "-1000"), flow("2025-01-01", "1100")],
            id="under a day",
        ),
        pytest.param(
            [flow("2025-01-01", "-1000"), flow("2026-01-01", "-100")],
            id="money only out",
        ),
        pytest.param(
            [flow("2025-01-01", "1000"), flow("2026-01-01", "100")],
            id="money only in",
        ),
        pytest.param(
            [
                flow("2025-01-01", "-1000"),
                flow("2025-07-01", "3000"),
                flow("2026-01-01", "-2300"),
            ],
            id="no rate explains it",
        ),
    ],
)
def test_no_xirr_without_a_solution_or_a_day_of_history(
    flows: list[tuple[date, Decimal]],
) -> None:
    assert xirr(flows) is None


def event(
    kind: str,
    day: str,
    units: str | None,
    amount: str | None,
    charges: str = "0",
) -> Event:
    return Event(
        kind,
        date.fromisoformat(day),
        None if units is None else Decimal(units),
        None if amount is None else Decimal(amount),
        Decimal(charges),
    )


def test_a_holding_with_two_buys_a_partial_sell_and_a_dividend() -> None:
    book = replay(
        [
            event("buy", "2025-01-01", "10", "1000", charges="15"),
            event("buy", "2025-07-01", "10", "1000"),
            event("dividend", "2025-10-01", None, "50"),
            event("sell", "2026-01-01", "5", "600", charges="10"),
        ]
    )

    # 15 units worth 1,676.95 two years in is what 10% a year grows to.
    result = returns(book.holdings[FUND].flows, Decimal("1676.95"), date(2027, 1, 1))

    assert result == pytest.approx(Decimal(10), abs=Decimal("0.001"))


def test_a_merged_holding_keeps_the_buys_of_the_instrument_it_came_from() -> None:
    book = replay(
        [
            event("buy", "2025-01-01", "10", "1000"),
            Event("merger", date(2025, 6, 1), None, None, new_instrument_id=NEW_FUND),
        ]
    )

    assert returns(book.holdings[FUND].flows, Decimal(0), date(2026, 1, 1)) is None
    result = returns(book.holdings[NEW_FUND].flows, Decimal(1100), date(2026, 1, 1))
    assert result == pytest.approx(Decimal(10), abs=Decimal("0.0001"))


def test_stock_splits_and_bonuses_move_no_money() -> None:
    book = replay(
        [
            event("buy", "2025-01-01", "10", "1000"),
            event("stock_split", "2025-03-01", "2", None),
            event("bonus", "2025-04-01", "5", None),
        ]
    )

    result = returns(book.holdings[FUND].flows, Decimal(1100), date(2026, 1, 1))

    assert result == pytest.approx(Decimal(10), abs=Decimal("0.0001"))
