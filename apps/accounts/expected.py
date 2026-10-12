"""Expected: what Upcoming Occurrences and waiting Drafts are set to move.

The Forecast and Budgets both find what is coming up here, so they agree.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Max, QuerySet

from apps.accounts.models import Account, AccountKind
from apps.quick_add.models import Draft, DraftSplit
from apps.schedules.models import Occurrence, Schedule, ScheduleSplit
from apps.schedules.repeat import due_dates


def upcoming_due(start: date, end: date) -> list[tuple[date, Schedule]]:
    """Each active Schedule's Upcoming due dates by the end.

    Occurrences are only stored DAYS_AHEAD, so later due dates are worked out
    from the Schedule, after its last stored Occurrence.
    """
    schedules = (
        Schedule.objects.filter(active=True)
        .select_related("party")
        .prefetch_related("splits")
        .annotate(last_due=Max("occurrences__due_date"))
    )
    by_pk = {schedule.pk: schedule for schedule in schedules}
    found: list[tuple[date, Schedule]] = [
        (occurrence.due_date, by_pk[occurrence.schedule_id])
        for occurrence in Occurrence.objects.filter(
            status=Occurrence.Status.UPCOMING,
            schedule__in=by_pk,
            due_date__lte=end,
        )
    ]
    for schedule in schedules:
        since = (
            schedule.last_due + timedelta(days=1)
            if schedule.last_due
            else max(filter(None, [schedule.start_date, schedule.resumed_on, start]))
        )
        found += [(when, schedule) for when in due_dates(schedule, since, end)]
    return found


def waiting_drafts(end: date) -> QuerySet[Draft]:
    """The waiting Drafts dated by the end, however long ago."""
    return (
        Draft.objects.waiting()
        .filter(date__lte=end)
        .select_related("party")
        .prefetch_related("splits")
    )


def expected_by_account(start: date, end: date) -> dict[int, Decimal]:
    """What each Expense Account is set to receive from start to end, by pk.

    Counts Upcoming Occurrences due and waiting Drafts dated in the range. Unlike
    the Forecast, an open amount adds nothing rather than being estimated.
    """
    splits: list[ScheduleSplit | DraftSplit] = [
        split
        for when, schedule in upcoming_due(start, end)
        if when >= start
        for split in schedule.splits.all()
    ]
    splits += [
        split
        for draft in waiting_drafts(end).filter(date__gte=start)
        for split in draft.splits.all()
    ]
    expense = set(
        Account.objects.filter(kind=AccountKind.EXPENSE).values_list("pk", flat=True)
    )
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for split in splits:
        if split.amount is None:
            continue
        if split.to_account_id in expense:
            totals[split.to_account_id] += split.amount
        if split.from_account_id in expense:
            totals[split.from_account_id] -= split.amount
    return dict(totals)
