from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import SuggestedSchedule
from apps.schedules.tests.conftest import make_schedule, paid

pytestmark = pytest.mark.django_db


def test_steady_monthly_payments_to_a_party_are_suggested() -> None:
    card = make_account("Card", "liability")
    streaming = make_account("Streaming", "expense")
    netflix = Party.objects.create(name="Netflix")
    evidence = paid(
        (card, streaming),
        netflix,
        ("649", date(2026, 7, 3)),
        ("649", date(2026, 8, 5)),
        ("699", date(2026, 9, 2)),
    )

    run_daily_job(date(2026, 9, 10))

    suggestion = SuggestedSchedule.objects.get()
    assert (
        suggestion.party,
        suggestion.from_account,
        suggestion.to_account,
        suggestion.amount,
        suggestion.unit,
        suggestion.status,
    ) == (netflix, card, streaming, Decimal(649), "month", "waiting")
    assert list(suggestion.evidence.all()) == evidence


def pay_netflix(*payments: tuple[str, date]) -> None:
    paid(
        (make_account("Card", "liability"), make_account("Streaming", "expense")),
        Party.objects.create(name="Netflix"),
        *payments,
    )


def suggested_units() -> list[str]:
    return [suggestion.unit for suggestion in SuggestedSchedule.objects.all()]


@pytest.mark.parametrize(
    ("dates", "unit"),
    [
        ((date(2026, 9, 1), date(2026, 9, 9), date(2026, 9, 15)), "week"),
        ((date(2026, 7, 31), date(2026, 8, 28), date(2026, 10, 1)), "month"),
        ((date(2024, 3, 1), date(2025, 3, 11), date(2026, 3, 1)), "year"),
    ],
    ids=["weekly", "monthly", "yearly"],
)
def test_payments_drifting_within_tolerance_are_suggested(
    dates: tuple[date, ...], unit: str
) -> None:
    pay_netflix(*(("649", when) for when in dates))

    run_daily_job(date(2026, 10, 10))

    assert suggested_units() == [unit]


@pytest.mark.parametrize(
    "dates",
    [
        (date(2026, 9, 1), date(2026, 9, 10), date(2026, 9, 17)),
        (date(2026, 7, 1), date(2026, 8, 5), date(2026, 9, 1)),
        (date(2024, 3, 1), date(2025, 3, 12), date(2026, 3, 1)),
    ],
    ids=["weekly", "monthly", "yearly"],
)
def test_payments_drifting_beyond_tolerance_are_not_suggested(
    dates: tuple[date, ...],
) -> None:
    pay_netflix(*(("649", when) for when in dates))

    run_daily_job(date(2026, 10, 10))

    assert suggested_units() == []


def test_two_payments_are_not_enough() -> None:
    pay_netflix(("649", date(2026, 8, 5)), ("649", date(2026, 9, 5)))

    run_daily_job(date(2026, 10, 10))

    assert suggested_units() == []


@pytest.mark.parametrize(
    ("amounts", "suggested"),
    [(("1000", "850", "1150"), True), (("1000", "849", "1000"), False)],
    ids=["within", "beyond"],
)
def test_amounts_must_stay_within_15_percent_of_the_median(
    amounts: tuple[str, ...], *, suggested: bool
) -> None:
    dates = (date(2026, 7, 5), date(2026, 8, 5), date(2026, 9, 5))
    pay_netflix(*zip(amounts, dates, strict=True))

    run_daily_job(date(2026, 10, 10))

    assert suggested_units() == (["month"] if suggested else [])


def test_only_the_latest_steady_run_is_evidence() -> None:
    card = make_account("Card", "liability")
    streaming = make_account("Streaming", "expense")
    netflix = Party.objects.create(name="Netflix")
    paid((card, streaming), netflix, ("2000", date(2026, 2, 17)))
    evidence = paid(
        (card, streaming),
        netflix,
        ("649", date(2026, 7, 5)),
        ("649", date(2026, 8, 5)),
        ("649", date(2026, 9, 5)),
    )

    run_daily_job(date(2026, 10, 10))

    assert list(SuggestedSchedule.objects.get().evidence.all()) == evidence


def test_payments_a_schedule_already_covers_are_not_suggested() -> None:
    card = make_account("Card", "liability")
    streaming = make_account("Streaming", "expense")
    netflix = Party.objects.create(name="Netflix")
    make_schedule((card, streaming, None), party=netflix, active=False)
    paid(
        (card, streaming),
        netflix,
        ("649", date(2026, 7, 5)),
        ("649", date(2026, 8, 5)),
        ("649", date(2026, 9, 5)),
    )

    run_daily_job(date(2026, 10, 10))

    assert suggested_units() == []


def test_a_second_run_suggests_nothing_new() -> None:
    pay_netflix(
        ("649", date(2026, 7, 5)), ("649", date(2026, 8, 5)), ("649", date(2026, 9, 5))
    )
    run_daily_job(date(2026, 10, 10))

    run_daily_job(date(2026, 10, 10))

    assert suggested_units() == ["month"]


def test_a_waiting_suggestion_proposes_no_drafts() -> None:
    pay_netflix(
        ("649", date(2026, 7, 5)), ("649", date(2026, 8, 5)), ("649", date(2026, 9, 5))
    )

    run_daily_job(date(2026, 10, 10))
    run_daily_job(date(2026, 11, 10))

    assert SuggestedSchedule.objects.get().status == "waiting"
    assert not Draft.objects.exists()
