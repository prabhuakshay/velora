"""Views for listing, editing, pausing and ending Schedules."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.schedules.forms import (
    ScheduleForm,
    ScheduleSplitFormSet,
    has_open_amount,
)
from apps.schedules.models import Occurrence, Schedule
from apps.schedules.occurrences import regenerate
from apps.schedules.repeat import months_after
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _initial_from(transaction: Transaction | None) -> dict[str, Any]:
    """The Schedule form's initial data copied from a Transaction, if any."""
    if transaction is None:
        return {}
    splits = [
        {
            "from_account": split.from_account_id,
            "to_account": split.to_account_id,
            "amount": split.amount,
        }
        for split in transaction.splits.all()
    ]
    return {
        "form": {
            "party": transaction.party_id,
            "description": transaction.description,
            "start_date": months_after(transaction.date, 1),
        },
        "formset": splits,
    }


def _save_schedule(
    request: HttpRequest, schedule: Schedule, transaction: Transaction | None = None
) -> HttpResponseBase:
    """Show the Schedule form, or save it and lay out its Occurrences again."""
    data = request.POST if request.method == "POST" else None
    initial = _initial_from(transaction)
    form = ScheduleForm(data, instance=schedule, initial=initial.get("form"))
    formset = ScheduleSplitFormSet(
        data, instance=schedule, initial=initial.get("formset")
    )
    # The formset shows one blank row by default; make room for each copied one.
    formset.extra = max(len(initial.get("formset", [])) - formset.min_num, 0)
    # Validate both so errors show on the Schedule and its Splits at once.
    valid = data is not None and all([form.is_valid(), formset.is_valid()])
    if valid and form.cleaned_data["auto_post"] and has_open_amount(formset):
        form.add_error("auto_post", "Auto-post needs an amount on every Split.")
        valid = False
    if valid:
        with db_transaction.atomic():
            formset.instance = form.save()
            formset.save()
            regenerate(formset.instance, timezone.localdate())
        return redirect("schedule_detail", formset.instance.pk)
    return render(
        request,
        "schedules/schedule_form.html",
        {"form": form, "formset": formset, "schedule": schedule.pk and schedule},
    )


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
    """Describe a new Schedule, prefilled from a Transaction if one is given."""
    transaction_pk = request.GET.get("transaction", "")
    transaction = (
        get_object_or_404(Transaction, pk=transaction_pk)
        if transaction_pk.isdigit()
        else None
    )
    return _save_schedule(request, Schedule(), transaction)


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
