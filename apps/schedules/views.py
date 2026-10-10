"""Views for listing, editing, pausing and ending Schedules."""

from datetime import timedelta
from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.schedules.forms import ScheduleForm, ScheduleSplitFormSet
from apps.schedules.models import Occurrence, Schedule, SuggestedSchedule
from apps.schedules.occurrences import regenerate
from apps.schedules.suggestions import next_expected
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _save_schedule(
    request: HttpRequest,
    schedule: Schedule,
    suggestion: SuggestedSchedule | None = None,
) -> HttpResponseBase:
    """Show the Schedule form, or save it and lay out its Occurrences again.

    Given a suggestion, the form starts from it and saving confirms it.
    """
    data = request.POST if request.method == "POST" else None
    initial, split_initial = _initial_from(suggestion) if suggestion else ({}, [])
    form = ScheduleForm(data, instance=schedule, initial=initial)
    formset = ScheduleSplitFormSet(data, instance=schedule, initial=split_initial)
    # Validate both so errors show on the Schedule and its Splits at once.
    if data is not None and all([form.is_valid(), formset.is_valid()]):
        with db_transaction.atomic():
            formset.instance = form.save()
            formset.save()
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


def _initial_from(
    suggestion: SuggestedSchedule,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """The Schedule and its one Split as the suggestion describes them."""
    last_paid = suggestion.evidence.order_by("date").last()
    schedule = {
        "party": suggestion.party_id,
        "every": 1,
        "unit": suggestion.unit,
        "start_date": last_paid and next_expected(last_paid.date, suggestion.unit),
    }
    split = {
        "from_account": suggestion.from_account_id,
        "to_account": suggestion.to_account_id,
        "amount": suggestion.amount,
    }
    return schedule, [split]


@login_required
def schedule_list(request: HttpRequest) -> HttpResponseBase:
    """Every Schedule with its next due date and amount."""
    schedules = Schedule.objects.select_related("party").prefetch_related(
        "splits",
        Prefetch(
            "occurrences",
            queryset=Occurrence.objects.filter(status=Occurrence.Status.UPCOMING),
            to_attr="upcoming",
        ),
    )
    return render(
        request,
        "schedules/schedule_list.html",
        {"schedules": schedules, "today": timezone.localdate()},
    )


@login_required
def schedule_create(request: HttpRequest) -> HttpResponseBase:
    """Describe a new Schedule."""
    return _save_schedule(request, Schedule())


@login_required
def schedule_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Change a Schedule; only its Upcoming Occurrences follow the change."""
    return _save_schedule(request, get_object_or_404(Schedule, pk=pk))


@login_required
def schedule_split_row(request: HttpRequest) -> HttpResponse:
    """A blank Split row for the form's "add split" control."""
    total = request.GET.get("splits-TOTAL_FORMS", "")
    index = int(total) if total.isdigit() else 0
    split = ScheduleSplitFormSet().empty_form
    split.prefix = f"splits-{index}"
    return render(
        request,
        "transactions/split_row_added.html",
        {"split": split, "total": index + 1},
    )


@login_required
def schedule_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
    """The Schedule and its Occurrence history."""
    schedule = get_object_or_404(Schedule.objects.select_related("party"), pk=pk)
    today = timezone.localdate()
    occurrences = schedule.occurrences.all()
    return render(
        request,
        "schedules/schedule_detail.html",
        {
            "schedule": schedule,
            "splits": schedule.splits.select_related("from_account", "to_account"),
            "occurrences": occurrences,
            "next_due": occurrences.filter(status=Occurrence.Status.UPCOMING).first(),
            "ended": schedule.ends_on is not None and schedule.ends_on < today,
            "today": today,
        },
    )


def _change_state(pk: int, **changes: object) -> HttpResponseBase:
    """Save the changes and lay out the Schedule's Upcoming Occurrences again."""
    with db_transaction.atomic():
        schedule = get_object_or_404(Schedule.objects.select_for_update(), pk=pk)
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
    return _change_state(pk, active=True, resumed_on=timezone.localdate())


@login_required
@require_POST
def schedule_end(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Stop the Schedule for good: nothing falls due from today on."""
    return _change_state(pk, ends_on=timezone.localdate() - timedelta(days=1))


@login_required
def suggested_schedule_list(request: HttpRequest) -> HttpResponseBase:
    """The Suggested Schedules waiting for the user to confirm or dismiss."""
    suggestions = (
        SuggestedSchedule.objects.filter(status=SuggestedSchedule.Status.WAITING)
        .select_related("party", "from_account", "to_account")
        .prefetch_related(
            Prefetch("evidence", queryset=Transaction.objects.order_by("date"))
        )
    )
    return render(
        request,
        "schedules/suggested_schedule_list.html",
        {"suggestions": suggestions},
    )


def _waiting(pk: int) -> SuggestedSchedule:
    return get_object_or_404(
        SuggestedSchedule.objects.select_for_update(),
        pk=pk,
        status=SuggestedSchedule.Status.WAITING,
    )


@login_required
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
