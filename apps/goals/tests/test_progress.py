from decimal import Decimal

from apps.goals.progress import (
    Counted,
    Share,
    count_shares,
    percent_left,
    unallocated,
)


def percent(value: str) -> Share:
    return Share(percent=Decimal(value))


def fixed(value: str) -> Share:
    return Share(amount=Decimal(value))


def counts(value: str, *shares: Share) -> list[tuple[Decimal, bool]]:
    return [(c.amount, c.capped) for c in count_shares(Decimal(value), shares)]


def test_a_percentage_counts_that_share_of_the_value() -> None:
    assert counts("1000.00", percent("25")) == [(Decimal("250.00"), False)]


def test_a_percentage_is_rounded_to_paise() -> None:
    assert counts("100.01", percent("33.33")) == [(Decimal("33.33"), False)]


def test_a_fixed_amount_within_the_value_counts_in_full() -> None:
    assert counts("1000", fixed("400")) == [(Decimal(400), False)]


def test_a_fixed_amount_above_the_value_is_capped_at_the_value() -> None:
    assert counts("1000", fixed("1500")) == [(Decimal(1000), True)]


def test_a_percentage_is_never_capped() -> None:
    assert counts("0", percent("100")) == [(Decimal(0), False)]


def test_a_source_worth_less_than_nothing_counts_nothing() -> None:
    assert counts("-200", percent("50"), fixed("100")) == [
        (Decimal(0), False),
        (Decimal(0), True),
    ]


def test_percentages_count_before_fixed_amounts() -> None:
    assert counts("1000", fixed("800"), percent("50")) == [
        (Decimal(500), True),
        (Decimal(500), False),
    ]


def test_a_fixed_amount_counts_only_what_earlier_ones_leave() -> None:
    assert counts("1000", fixed("600"), fixed("600"), fixed("100")) == [
        (Decimal(600), False),
        (Decimal(400), True),
        (Decimal(0), True),
    ]


def test_no_rupee_counts_twice() -> None:
    shares = [percent("40"), fixed("500"), percent("30"), fixed("700")]

    total = sum((c.amount for c in count_shares(Decimal(1000), shares)), Decimal(0))

    assert total == Decimal(1000)


def test_counted_is_what_a_share_counts_and_whether_it_was_capped() -> None:
    assert count_shares(Decimal(10), [fixed("5")]) == [
        Counted(amount=Decimal(5), capped=False)
    ]


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
