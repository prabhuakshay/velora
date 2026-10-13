from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from apps.investments.replay import OversoldError, cash, market_value, replay

FUND = 1
NEW_FUND = 2


@dataclass(frozen=True)
class Event:
    kind: str
    date: date
    units: Decimal | None
    amount: Decimal | None
    charges: Decimal = Decimal(0)
    instrument_id: int = FUND
    new_instrument_id: int | None = None


def buy(day: int, units: str, amount: str, charges: str = "0") -> Event:
    return Event(
        "buy", date(2026, 1, day), Decimal(units), Decimal(amount), Decimal(charges)
    )


def sell(day: int, units: str, amount: str, charges: str = "0") -> Event:
    return Event(
        "sell", date(2026, 1, day), Decimal(units), Decimal(amount), Decimal(charges)
    )


def test_a_buy_starts_a_lot_costing_its_amount_plus_charges() -> None:
    book = replay([buy(5, "10", "1000", "15")])

    holding = book.holdings[FUND]
    assert holding.units == Decimal(10)
    assert holding.cost_basis == Decimal(1015)


def test_a_sell_takes_the_oldest_lots_first_and_pro_rates_a_partly_sold_one() -> None:
    book = replay(
        [
            buy(1, "10", "1000"),
            buy(2, "10", "1500"),
            sell(3, "15", "2400", "10"),
        ]
    )

    holding = book.holdings[FUND]
    assert holding.units == Decimal(5)
    assert holding.cost_basis == Decimal(750)
    assert [(lot.date.day, lot.units) for lot in holding.lots] == [(2, Decimal(5))]
    # Proceeds 2390 less the cost of 10 units at 100 and 5 at 150.
    assert holding.realized == Decimal(640)


def test_selling_everything_closes_every_lot() -> None:
    book = replay([buy(1, "3", "300"), sell(2, "3", "330")])

    holding = book.holdings[FUND]
    assert holding.lots == []
    assert holding.cost_basis == 0
    assert holding.realized == Decimal(30)


def test_events_replay_in_date_order_whatever_order_they_come_in() -> None:
    book = replay([sell(3, "5", "600"), buy(1, "10", "1000")])

    assert book.holdings[FUND].units == Decimal(5)


def test_a_same_day_buy_comes_before_the_sell() -> None:
    book = replay([sell(1, "5", "500"), buy(1, "5", "400")])

    assert book.holdings[FUND].realized == Decimal(100)


def test_a_sell_of_more_than_is_held_on_its_date_is_refused() -> None:
    too_many = sell(3, "4", "400")

    with pytest.raises(OversoldError) as refused:
        replay([buy(1, "3", "300"), too_many, buy(9, "10", "1000")])

    assert refused.value.event == too_many
    assert refused.value.held == Decimal(3)


def test_replay_until_a_date_leaves_later_events_out() -> None:
    book = replay([buy(1, "10", "1000"), buy(9, "5", "600")], until=date(2026, 1, 8))

    assert book.holdings[FUND].units == Decimal(10)


def test_cash_is_balance_less_cost_basis_plus_gains_after_the_opening_date() -> None:
    book = replay(
        [
            buy(1, "10", "1000"),
            sell(2, "2", "260"),  # on the Opening Balance date: gain 60 inside it
            sell(5, "3", "390"),  # gain 90 after it
        ]
    )

    # Balance 2000 less 500 still held, plus the later gain.
    assert cash(Decimal(2000), book, opened=date(2026, 1, 2)) == Decimal(1590)


def test_cash_without_events_is_the_balance() -> None:
    assert cash(Decimal(500), replay([]), opened=date(2026, 1, 1)) == Decimal(500)


def test_market_value_is_cash_plus_units_at_their_price() -> None:
    other = Event("buy", date(2026, 1, 1), Decimal(2), Decimal(50), instrument_id=2)
    book = replay([buy(1, "3.5", "300"), other])

    value = market_value(Decimal(100), book, {FUND: Decimal("120.1234")})

    # 3.5 x 120.1234 = 420.43, plus 50 at cost for the unpriced one.
    assert value == Decimal("570.43")


def split(day: int, ratio: str) -> Event:
    return Event("stock_split", date(2026, 1, day), Decimal(ratio), None)


def test_a_stock_split_multiplies_units_and_keeps_cost_basis_for_a_later_sell() -> None:
    book = replay([buy(1, "10", "1000"), split(2, "5"), sell(3, "20", "500")])

    holding = book.holdings[FUND]
    assert holding.units == Decimal(30)
    assert holding.cost_basis == Decimal(600)
    # 20 of the 50 split units cost 400.
    assert holding.realized == Decimal(100)


def bonus(day: int, units: str) -> Event:
    return Event("bonus", date(2026, 1, day), Decimal(units), None)


def test_a_bonus_starts_a_zero_cost_lot_that_a_later_sell_takes_after_older_lots() -> (
    None
):
    book = replay([buy(1, "10", "1000"), bonus(2, "5"), sell(3, "12", "1440")])

    holding = book.holdings[FUND]
    assert [(lot.date.day, lot.units, lot.cost) for lot in holding.lots] == [
        (2, Decimal(3), Decimal(0))
    ]
    # The 10 bought cost 1000 and the 2 bonus units nothing.
    assert holding.realized == Decimal(440)


def merger(day: int) -> Event:
    return Event("merger", date(2026, 1, day), None, None, new_instrument_id=NEW_FUND)


def test_a_merger_moves_every_lot_to_the_new_instrument_keeping_date_and_cost() -> None:
    already = Event(
        "buy", date(2026, 1, 2), Decimal(1), Decimal(200), instrument_id=NEW_FUND
    )
    book = replay(
        [
            buy(1, "10", "1000"),
            already,
            buy(3, "5", "600"),
            sell(4, "2", "260"),
            merger(5),
        ]
    )

    assert book.holdings[FUND].lots == []
    assert book.holdings[FUND].realized == Decimal(60)
    new = book.holdings[NEW_FUND]
    assert [(lot.date.day, lot.units, lot.cost) for lot in new.lots] == [
        (1, Decimal(8), Decimal(800)),
        (2, Decimal(1), Decimal(200)),
        (3, Decimal(5), Decimal(600)),
    ]


def test_a_sell_after_a_merger_takes_the_new_instruments_oldest_lots() -> None:
    sale = Event(
        "sell", date(2026, 1, 6), Decimal(12), Decimal(1500), instrument_id=NEW_FUND
    )
    book = replay([buy(1, "10", "1000"), buy(3, "5", "600"), merger(5), sale])

    new = book.holdings[NEW_FUND]
    assert new.units == Decimal(3)
    assert new.cost_basis == Decimal(360)
    # 10 at 100 and 2 at 120.
    assert new.realized == Decimal(260)


def dividend(day: int, amount: str, instrument_id: int = FUND) -> Event:
    return Event(
        "dividend",
        date(2026, 1, day),
        None,
        Decimal(amount),
        instrument_id=instrument_id,
    )


def test_dividends_add_up_on_their_holding_without_changing_lots() -> None:
    book = replay([buy(1, "10", "1000"), dividend(2, "50"), dividend(3, "25.5")])

    holding = book.holdings[FUND]
    assert holding.dividends == Decimal("75.5")
    assert holding.units == Decimal(10)
    assert holding.cost_basis == Decimal(1000)


def test_same_day_events_replay_buy_bonus_split_merger_dividend_then_sell() -> None:
    sale = Event(
        "sell", date(2026, 1, 1), Decimal(29), Decimal(2900), instrument_id=NEW_FUND
    )
    book = replay(
        [
            sale,
            dividend(1, "40", NEW_FUND),
            merger(1),
            split(1, "2"),
            bonus(1, "5"),
            buy(1, "10", "1000"),
        ]
    )

    # 10 bought and 5 free make 15, split to 30, merged, then 29 sold.
    new = book.holdings[NEW_FUND]
    assert new.units == Decimal(1)
    assert new.dividends == Decimal(40)
    # The 20 bought units cost 1000 and the 9 bonus units nothing.
    assert new.realized == Decimal(1900)
