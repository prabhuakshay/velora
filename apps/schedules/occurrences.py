"""Laying out a Schedule's Occurrences and proposing Drafts for due ones."""

from datetime import date, timedelta

from django.db import transaction as db_transaction

from apps.quick_add.models import Draft, DraftSplit
from apps.schedules.models import Occurrence, Schedule
from apps.schedules.repeat import due_dates

# Occurrences exist this far ahead, the length of the Forecast.
DAYS_AHEAD = 30


def materialise(schedule: Schedule, today: date) -> None:
    """Store the Occurrences due after the last stored one, up to DAYS_AHEAD.

    Never fills in before the last stored Occurrence, so dates dropped by an
    edit or a pause stay dropped.
    """
    since = max(filter(None, [schedule.start_date, schedule.resumed_on]))
    last = schedule.occurrences.order_by("due_date").last()
    if last:
        since = max(since, last.due_date + timedelta(days=1))
    Occurrence.objects.bulk_create(
        Occurrence(schedule=schedule, due_date=due)
        for due in due_dates(schedule, since, today + timedelta(days=DAYS_AHEAD))
    )


def regenerate(schedule: Schedule, today: date) -> None:
    """Lay out the Upcoming Occurrences again, after the Schedule changed."""
    schedule.occurrences.filter(status=Occurrence.Status.UPCOMING).delete()
    if schedule.active:
        materialise(schedule, today)


def materialise_occurrences(today: date) -> None:
    """Lay out every active Schedule's Occurrences up to DAYS_AHEAD."""
    for schedule in Schedule.objects.filter(active=True):
        materialise(schedule, today)


@db_transaction.atomic
def propose_draft(occurrence: Occurrence) -> None:
    """Copy the Schedule into a Draft for the Occurrence, which is now Drafted."""
    schedule = occurrence.schedule
    draft = Draft.objects.create(
        source=Draft.Source.SCHEDULE,
        occurrence=occurrence,
        date=occurrence.due_date,
        party=schedule.party,
        description=schedule.description,
    )
    DraftSplit.objects.bulk_create(
        DraftSplit(
            draft=draft,
            from_account=split.from_account,
            to_account=split.to_account,
            amount=split.amount,
        )
        for split in schedule.splits.all()
    )
    occurrence.status = Occurrence.Status.DRAFTED
    occurrence.save(update_fields=["status"])


def propose_due_drafts(today: date) -> None:
    """Propose a Draft for every Upcoming Occurrence due by today."""
    due = Occurrence.objects.filter(
        status=Occurrence.Status.UPCOMING,
        due_date__lte=today,
        schedule__active=True,
    ).select_related("schedule")
    for occurrence in due:
        propose_draft(occurrence)
