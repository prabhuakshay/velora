from decimal import Decimal

from apps.goals.progress import (
    Share,
    counted,
    goal_progress,
    is_capped,
    percent_left,
    unallocated,
)


def percent(value: str) -> Share:
    return Share(percent=Decimal(value))


def fixed(value: str) -> Share:
    return Share(amount=Decimal(value))


def test_a_percentage_counts_that_share_of_the_value() -> None:
    assert counted(percent("25"), Decimal("1000.00")) == Decimal("250.00")


def test_a_percentage_is_rounded_to_paise() -> None:
    assert counted(percent("33.33"), Decimal("100.01")) == Decimal("33.33")


def test_a_fixed_amount_within_the_value_counts_in_full() -> None:
    assert counted(fixed("400"), Decimal(1000)) == Decimal(400)
    assert not is_capped(fixed("400"), Decimal(1000))


def test_a_fixed_amount_above_the_value_is_capped_at_the_value() -> None:
    assert counted(fixed("1500"), Decimal(1000)) == Decimal(1000)
    assert is_capped(fixed("1500"), Decimal(1000))


def test_a_percentage_is_never_capped() -> None:
    assert not is_capped(percent("100"), Decimal(0))


def test_a_source_worth_less_than_nothing_counts_nothing() -> None:
    assert counted(percent("50"), Decimal(-200)) == 0
    assert counted(fixed("100"), Decimal(-200)) == 0
    assert is_capped(fixed("100"), Decimal(-200))


def test_goal_progress_adds_what_each_allocation_counts() -> None:
    progress = goal_progress(
        [
            (percent("50"), Decimal(1000)),
            (fixed("300"), Decimal(200)),
            (fixed("100"), Decimal(5000)),
        ]
    )

    assert progress == Decimal(800)


def test_a_goal_with_no_allocations_has_no_progress() -> None:
    assert goal_progress([]) == 0


def test_unallocated_is_what_no_goal_counts() -> None:
    assert unallocated(Decimal(1000), [percent("30"), fixed("200")]) == Decimal(500)


def test_unallocated_is_never_below_nothing() -> None:
    assert unallocated(Decimal(1000), [percent("60"), fixed("700")]) == 0
    assert unallocated(Decimal(-50), []) == 0


def test_percent_left_ignores_fixed_amounts() -> None:
    assert percent_left([percent("30"), fixed("500"), percent("12.5")]) == Decimal(
        "57.5"
    )
    assert percent_left([]) == 100
