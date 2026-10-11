"""Views for listing, editing, pausing and ending Schedules."""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Count, Min, OuterRef, Prefetch, Q, Subquery, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.dates import months_after
from apps.core.views import blank_split_row, paginate
from apps.schedules.forms import (
    ScheduleForm,
    ScheduleSplitFormSet,
    has_open_amount,
)
from apps.schedules.models import (
    Occurrence,
    Schedule,
    SuggestedSchedule,
)
from apps.schedules.occurrences import regenerate
from apps.schedules.overview import (
    a_month,
    coming_up,
    due_dates_left,
    final_due_date,
    later_due_dates,
    record,
)
from apps.schedules.repeat import units_after
from apps.schedules.subscriptions import (
    subscription_costs,
    times_a_year,
    yearly_total,
)
from apps.transactions.models import Transaction
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


type Initial = tuple[dict[str, object], list[dict[str, object]]]


def _initial_from_transaction(transaction: Transaction) -> Initial:
    """The Schedule and its Splits copied from a Transaction, due a month on."""
    schedule: dict[str, object] = {
        "party": transaction.party_id,
        "description": transaction.description,
        "start_date": months_after(transaction.date, 1),
    }
    splits = [
        {
            "from_account": split.from_account_id,
            "to_account": split.to_account_id,
            "amount": split.amount,
        }
        for split in transaction.splits.all()
    ]
    return schedule, splits


def _save_schedule(
    request: HttpRequest,
    schedule: Schedule,
    suggestion: SuggestedSchedule | None = None,
    initial: Initial = ({}, []),
) -> HttpResponseBase:
    """Show the Schedule form, or save it and lay out its Occurrences again.

    Given a suggestion, the form starts from it and saving confirms it.
    """
    data = request.POST if request.method == "POST" else None
    if suggestion:
        initial = _initial_from(suggestion)
    form = ScheduleForm(data, instance=schedule, initial=initial[0])
    formset = ScheduleSplitFormSet(data, instance=schedule, initial=initial[1])
    # The formset shows one blank row by default; make room for each copied one.
    formset.extra = max(len(initial[1]) - formset.min_num, 0)
    # Validate both so errors show on the Schedule and its Splits at once.
    valid = data is not None and all([form.is_valid(), formset.is_valid()])
    if valid and form.cleaned_data["auto_post"] and has_open_amount(formset):
        form.add_error("auto_post", "Auto-post needs an amount on every Split.")
        valid = False
    if valid:
        with db_transaction.atomic():
            formset.instance = form.save()
            formset.save()
            Schedule.objects.select_for_update().get(pk=formset.instance.pk)
            regenerate(formset.instance, timezone.localdate())
            if suggestion:
                suggestion.status = SuggestedSchedule.Status.CONFIRMED
                suggestion.save(update_fields=["status"])
        return redirect("schedule_detail", formset.instance.pk)
    return render(
        request,
        "schedules/schedule_form.html",
        {
            "form": form,
            "formset": formset,
            "schedule": schedule.pk and schedule,
            "suggestion": suggestion,
        },
    )


def _initial_from(suggestion: SuggestedSchedule) -> Initial:
    """The Schedule and its one Split as the suggestion describes them."""
    last_paid = suggestion.evidence.order_by("date").last()
    schedule = {
        "party": suggestion.party_id,
        "every": 1,
        "unit": suggestion.unit,
        "start_date": last_paid and units_after(last_paid.date, suggestion.unit, 1),
    }
    split = {
        "from_account": suggestion.from_account_id,
        "to_account": suggestion.to_account_id,
        "amount": suggestion.amount,
    }
    return schedule, [split]


# Each Split's Accounts, which tell an income or a Transfer Schedule apart.
SPLIT_ACCOUNTS = ("splits__from_account", "splits__to_account")


@login_required
def schedule_list(request: HttpRequest) -> HttpResponseBase:
    """Every Schedule by what it does next, and what falls due soon."""
    today = timezone.localdate()
    past = Occurrence.objects.filter(schedule=OuterRef("pk")).exclude(
        status=Occurrence.Status.UPCOMING
    )
    schedules = (
        Schedule.objects.select_related("party")
        .prefetch_related(*SPLIT_ACCOUNTS)
        .annotate(
            waiting=Count(
                "occurrences", filter=Q(occurrences__status=Occurrence.Status.DRAFTED)
            ),
            last_status=Subquery(past.order_by("-due_date").values("status")[:1]),
            next_due=Min(
                "occurrences__due_date",
                filter=Q(occurrences__status=Occurrence.Status.UPCOMING),
            ),
        )
        # Meta.ordering is dropped once an aggregate groups the rows.
        .order_by("pk")
    )
    on, paused, ended = [], [], []
    for schedule in schedules:
        if schedule.has_ended(today):
            ended.append(schedule)
        elif schedule.active:
            # Occurrences are laid out only 30 days ahead; look past them.
            if schedule.next_due is None:
                schedule.next_due = next(
                    iter(later_due_dates(schedule, today, 1)), None
                )
            on.append(schedule)
        else:
            paused.append(schedule)
    soon = Occurrence.objects.filter(
        status=Occurrence.Status.UPCOMING,
        due_date__lte=today + timedelta(days=30),
    ).prefetch_related(*(f"schedule__{lookup}" for lookup in SPLIT_ACCOUNTS))
    return render(
        request,
        "schedules/schedule_list.html",
        {
            # The next due first; one with nothing upcoming goes last.
            "on": sorted(on, key=lambda s: s.next_due or date.max),
            "stopped": [("Paused", paused), ("Ended", ended)],
            "stats": [
                ("Next 7 days", coming_up(soon, today + timedelta(days=7))),
                ("Next 30 days", coming_up(soon, today + timedelta(days=30))),
                ("Average month", a_month(on, today)),
            ],
            "horizon": today + timedelta(days=30),
            "today": today,
        },
    )


@login_required
@blocked_in_privacy_mode
def schedule_create(request: HttpRequest) -> HttpResponseBase:
    """Describe a new Schedule, prefilled from a Transaction if one is given."""
    transaction_pk = request.GET.get("transaction", "")
    transaction = (
        get_object_or_404(Transaction, pk=transaction_pk)
        if transaction_pk.isdigit()
        else None
    )
    return _save_schedule(
        request,
        Schedule(),
        initial=_initial_from_transaction(transaction) if transaction else ({}, []),
    )


@login_required
@blocked_in_privacy_mode
def schedule_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Change a Schedule; only its Upcoming Occurrences follow the change."""
    return _save_schedule(request, get_object_or_404(Schedule, pk=pk))


@login_required
def schedule_split_row(request: HttpRequest) -> HttpResponse:
    """A blank Split row for the form's "add split" control."""
    return blank_split_row(request, ScheduleSplitFormSet)


@login_required
def schedule_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
    """The Schedule, what falls due next and how its past Occurrences went."""
    schedule = get_object_or_404(
        Schedule.objects.select_related("party").prefetch_related(*SPLIT_ACCOUNTS),
        pk=pk,
    )
    today = timezone.localdate()
    upcoming = schedule.occurrences.filter(status=Occurrence.Status.UPCOMING)
    history = (
        schedule.occurrences.exclude(status=Occurrence.Status.UPCOMING)
        .select_related("draft")
        .annotate(paid=Sum("transaction__splits__amount"))
        .order_by("-due_date", "-pk")
    )
    final = final_due_date(schedule)
    amount = schedule.amount
    yearly = (
        amount * times_a_year(schedule, today)
        if schedule.is_subscription and amount is not None
        else None
    )
    return render(
        request,
        "schedules/schedule_detail.html",
        {
            "schedule": schedule,
            "amount": amount,
            "upcoming": upcoming,
            "later": later_due_dates(schedule, today),
            "page": paginate(request, history),
            "record": record(schedule),
            "final": final,
            "left": final and due_dates_left(schedule, today, final),
            "yearly": yearly,
            "monthly": yearly and yearly / 12,
            "ended": schedule.has_ended(today),
            "today": today,
        },
    )


def _change_state(
    pk: int,
    unless: Callable[[Schedule], bool] = lambda _: False,
    **changes: object,
) -> HttpResponseBase:
    """Save the changes and lay out the Schedule's Upcoming Occurrences again.

    Changes nothing when unless holds for the Schedule.
    """
    with db_transaction.atomic():
        schedule = get_object_or_404(Schedule.objects.select_for_update(), pk=pk)
        if unless(schedule):
            return redirect("schedule_detail", pk)
        for name, value in changes.items():
            setattr(schedule, name, value)
        schedule.save()
        regenerate(schedule, timezone.localdate())
    return redirect("schedule_detail", pk)


@login_required
@require_POST
def schedule_pause(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Stop proposing Drafts until resumed."""
    return _change_state(pk, active=False)


@login_required
@require_POST
def schedule_resume(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Propose Drafts again from today, never for dates while paused."""
    today = timezone.localdate()
    return _change_state(
        pk, lambda schedule: schedule.active, active=True, resumed_on=today
    )


@login_required
@require_POST
def schedule_end(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Stop the Schedule for good: nothing falls due from today on."""
    today = timezone.localdate()
    return _change_state(
        pk,
        lambda schedule: schedule.has_ended(today),
        ends_on=today - timedelta(days=1),
    )


@login_required
def subscription_list(request: HttpRequest) -> HttpResponseBase:
    """Every Subscription with its cost, the totals and the trials still running."""
    today = timezone.localdate()
    rows = subscription_costs(today)
    total = yearly_total(rows)
    trials = sorted(
        (
            row.schedule
            for row in rows
            if row.counted
            and row.schedule.trial_ends_on
            and row.schedule.trial_ends_on >= today
        ),
        key=lambda schedule: schedule.trial_ends_on or today,
    )
    return render(
        request,
        "schedules/subscription_list.html",
        {
            "page": paginate(request, rows),
            "counted": sum(row.counted for row in rows),
            "yearly_total": total,
            "monthly_total": total / 12,
            "trials": trials,
            "today": today,
        },
    )


@login_required
def suggested_schedule_list(request: HttpRequest) -> HttpResponseBase:
    """The Suggested Schedules waiting for the user to confirm or dismiss."""
    suggestions = (
        SuggestedSchedule.objects.filter(status=SuggestedSchedule.Status.WAITING)
        .select_related("party", "from_account", "to_account")
        .prefetch_related(
            Prefetch(
                "evidence",
                queryset=Transaction.objects.order_by("date").annotate(
                    total=Sum("splits__amount")
                ),
            )
        )
    )
    rows = []
    for suggestion in suggestions:
        last = list(suggestion.evidence.all())[-1:]
        expected = last and units_after(last[0].date, suggestion.unit, 1)
        rows.append((suggestion, expected or None))
    return render(
        request,
        "schedules/suggested_schedule_list.html",
        {"rows": rows, "today": timezone.localdate()},
    )


def _waiting(pk: int) -> SuggestedSchedule:
    return get_object_or_404(
        SuggestedSchedule.objects.select_for_update(),
        pk=pk,
        status=SuggestedSchedule.Status.WAITING,
    )


@login_required
@blocked_in_privacy_mode
@db_transaction.atomic
def suggested_schedule_confirm(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Turn a Suggested Schedule, adjusted as the user likes, into a Schedule."""
    return _save_schedule(request, Schedule(), _waiting(pk))


@login_required
@require_POST
def suggested_schedule_dismiss(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Drop a Suggested Schedule for good; detection never offers it again."""
    with db_transaction.atomic():
        suggestion = _waiting(pk)
        suggestion.status = SuggestedSchedule.Status.DISMISSED
        suggestion.save(update_fields=["status"])
    return redirect("suggested_schedule_list")
