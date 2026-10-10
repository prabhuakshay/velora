from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import account_url, make_account
from apps.classification.models import Party
from apps.schedules.daily_job import run_daily_job
from apps.schedules.models import Schedule, SuggestedSchedule
from apps.schedules.tests.conftest import paid, schedule_form_data
from apps.users.tests.conftest import privacy_mode_off_url, turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def suggest(
    source: Account | None = None, destination: Account | None = None
) -> SuggestedSchedule:
    """A waiting Suggested Schedule for monthly Netflix payments, the last on 5 Sep."""
    paid(
        (
            source or make_account("Card", "liability"),
            destination or make_account("Streaming", "expense"),
        ),
        Party.objects.create(name="Netflix"),
        ("649", date(2026, 7, 5)),
        ("649", date(2026, 8, 5)),
        ("649", date(2026, 9, 5)),
    )
    run_daily_job(date(2026, 9, 10))
    return SuggestedSchedule.objects.get()


def test_waiting_suggestions_are_listed_for_review(signed_in: Client) -> None:
    suggestion = suggest()

    body = signed_in.get(reverse("suggested_schedule_list")).content.decode()

    assert "Netflix" in body
    assert "₹649.00" in body
    assert "Every month" in body
    assert "5 Sep 2026" in body
    assert reverse("suggested_schedule_confirm", args=[suggestion.pk]) in body
    assert reverse("suggested_schedule_dismiss", args=[suggestion.pk]) in body


def test_the_waiting_count_shows_on_every_page(signed_in: Client) -> None:
    suggest()

    body = signed_in.get(reverse("index")).content.decode()

    assert "1 Suggested Schedule waiting" in body


def test_confirming_starts_from_the_suggestion(signed_in: Client) -> None:
    suggestion = suggest()

    response = signed_in.get(
        reverse("suggested_schedule_confirm", args=[suggestion.pk])
    )

    form = response.context["form"]
    split = response.context["formset"].forms[0]
    assert (
        form["party"].value(),
        form["start_date"].value(),
        form["every"].value(),
        form["unit"].value(),
    ) == (suggestion.party.pk, date(2026, 10, 5), 1, "month")
    assert (
        split["from_account"].value(),
        split["to_account"].value(),
        split["amount"].value(),
    ) == (suggestion.from_account.pk, suggestion.to_account.pk, Decimal(649))


def test_confirming_with_edits_creates_the_schedule(signed_in: Client) -> None:
    suggestion = suggest()
    card, streaming = suggestion.from_account, suggestion.to_account

    response = signed_in.post(
        reverse("suggested_schedule_confirm", args=[suggestion.pk]),
        schedule_form_data(
            (card, streaming, "699"),
            party=suggestion.party.pk,
            description="Netflix premium",
            start_date="2026-10-06",
        ),
    )

    schedule = Schedule.objects.get()
    assert response["Location"] == reverse("schedule_detail", args=[schedule.pk])
    assert (schedule.party, schedule.description, schedule.start_date) == (
        suggestion.party,
        "Netflix premium",
        date(2026, 10, 6),
    )
    assert [
        (split.from_account, split.to_account, split.amount)
        for split in schedule.splits.all()
    ] == [(card, streaming, Decimal(699))]
    suggestion.refresh_from_db()
    assert suggestion.status == SuggestedSchedule.Status.CONFIRMED


def test_confirming_follows_the_split_rules(signed_in: Client) -> None:
    suggestion = suggest()
    salary = make_account("Salary", "income")

    response = signed_in.post(
        reverse("suggested_schedule_confirm", args=[suggestion.pk]),
        schedule_form_data((suggestion.from_account, salary, "649")),
    )

    assert "An Income Account can only be a source." in response.content.decode()
    assert not Schedule.objects.exists()
    suggestion.refresh_from_db()
    assert suggestion.status == SuggestedSchedule.Status.WAITING


def test_a_dismissed_suggestion_never_returns(signed_in: Client) -> None:
    suggestion = suggest()

    response = signed_in.post(
        reverse("suggested_schedule_dismiss", args=[suggestion.pk])
    )
    run_daily_job(date(2026, 10, 6))

    assert response["Location"] == reverse("suggested_schedule_list")
    assert list(SuggestedSchedule.objects.values_list("status", flat=True)) == [
        SuggestedSchedule.Status.DISMISSED
    ]
    body = signed_in.get(reverse("suggested_schedule_list")).content.decode()
    assert "Netflix" not in body
    assert "Suggested Schedule waiting" not in body


def test_only_waiting_suggestions_can_be_confirmed_or_dismissed(
    signed_in: Client,
) -> None:
    suggestion = suggest()
    signed_in.post(reverse("suggested_schedule_dismiss", args=[suggestion.pk]))

    confirm = signed_in.get(reverse("suggested_schedule_confirm", args=[suggestion.pk]))
    dismiss = signed_in.post(
        reverse("suggested_schedule_dismiss", args=[suggestion.pk])
    )

    assert (confirm.status_code, dismiss.status_code) == (404, 404)


def test_merging_an_account_repoints_suggestions(signed_in: Client) -> None:
    old_card = make_account("Old card", "liability")
    card = make_account("Card", "liability")
    suggestion = suggest(source=old_card)

    signed_in.post(account_url("account_merge", old_card), {"target": card.pk})

    suggestion.refresh_from_db()
    assert suggestion.from_account == card


def test_suggestions_need_sign_in(client: Client) -> None:
    response = client.get(reverse("suggested_schedule_list"))

    assert response.status_code == 302


def test_confirming_sends_to_privacy_mode_off_page(signed_in: Client) -> None:
    card = make_account("Card", "liability")
    streaming = make_account("Streaming", "expense")
    suggestion = suggest(card, streaming)
    url = reverse("suggested_schedule_confirm", args=[suggestion.pk])
    turn_on(signed_in)

    get = signed_in.get(url)
    post = signed_in.post(url, schedule_form_data((card, streaming, "649")))

    for response in (get, post):
        assert response.status_code == 302
        assert response["Location"] == privacy_mode_off_url(url)
    assert not Schedule.objects.exists()
    suggestion.refresh_from_db()
    assert suggestion.status == SuggestedSchedule.Status.WAITING
