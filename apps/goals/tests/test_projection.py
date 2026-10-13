from datetime import date
from decimal import Decimal

from apps.goals.projection import (
    Contribution,
    inflated_target,
    monthly_rate,
    months_between,
    projection,
    required_monthly,
)

TWELVE = monthly_rate(Decimal(12))


def test_whole_months_between_two_dates() -> None:
    assert months_between(date(2026, 10, 13), date(2027, 10, 13)) == 12
    assert months_between(date(2026, 10, 13), date(2027, 10, 12)) == 11
    assert months_between(date(2026, 1, 31), date(2026, 2, 28)) == 1


def test_no_months_to_a_date_already_passed() -> None:
    assert months_between(date(2026, 10, 13), date(2025, 1, 1)) == 0


def test_the_target_is_inflated_to_the_target_date() -> None:
    assert inflated_target(Decimal(100000), Decimal(6), 24) == Decimal("112360.00")


def test_the_target_is_inflated_over_part_years() -> None:
    assert inflated_target(Decimal(100000), Decimal(6), 30) == Decimal("115681.70")


def test_a_target_date_already_reached_is_not_inflated() -> None:
    assert inflated_target(Decimal(100000), Decimal(6), 0) == Decimal(100000)


def test_progress_grows_at_the_expected_return() -> None:
    assert projection(Decimal(50000), TWELVE, 24, []) == Decimal("62720.00")


def test_progress_does_not_grow_with_no_months_left() -> None:
    assert projection(Decimal(50000), TWELVE, 0, []) == Decimal(50000)


def test_a_linked_schedule_adds_its_monthly_amount_as_an_annuity() -> None:
    sip = Contribution(monthly=Decimal(1000), months=12)

    assert projection(Decimal(0), TWELVE, 12, [sip]) == Decimal("12646.50")


def test_a_schedule_adds_without_growth_at_no_return() -> None:
    sip = Contribution(monthly=Decimal(1000), months=12)

    assert projection(Decimal(500), monthly_rate(Decimal(0)), 12, [sip]) == Decimal(
        12500
    )


def test_a_schedule_ending_before_the_target_date_stops_adding_but_keeps_growing() -> (
    None
):
    sip = Contribution(monthly=Decimal(1000), months=6)

    assert projection(Decimal(0), TWELVE, 12, [sip]) == Decimal("6502.35")


def test_a_schedule_never_adds_past_the_target_date() -> None:
    sip = Contribution(monthly=Decimal(1000), months=60)

    assert projection(Decimal(0), TWELVE, 12, [sip]) == Decimal("12646.50")


def test_progress_and_schedules_add_up() -> None:
    sip = Contribution(monthly=Decimal(1000), months=12)
    rent = Contribution(monthly=Decimal(1000), months=6)

    assert projection(Decimal(50000), TWELVE, 12, [sip, rent]) == Decimal("75148.85")


def test_the_required_monthly_investment_closes_the_gap() -> None:
    assert required_monthly(Decimal("12646.50"), TWELVE, 12) == Decimal("1000.00")


def test_the_required_monthly_investment_at_no_return() -> None:
    assert required_monthly(Decimal(12000), monthly_rate(Decimal(0)), 12) == Decimal(
        "1000.00"
    )


def test_no_monthly_investment_is_required_when_on_track() -> None:
    assert required_monthly(Decimal(0), TWELVE, 12) == 0
    assert required_monthly(Decimal(-500), TWELVE, 12) == 0


def test_the_whole_gap_is_required_with_under_a_month_left() -> None:
    assert required_monthly(Decimal(3000), TWELVE, 0) == Decimal(3000)
