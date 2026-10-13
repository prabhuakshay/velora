"""The Goals list, Goal pages and their Allocations."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.views import save_unique_name
from apps.goals.forms import AllocationForm, GoalForm
from apps.goals.models import Allocation, Goal
from apps.goals.summary import summarise
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase


@login_required
def goal_list(request: HttpRequest) -> HttpResponseBase:
    """Every Goal with its progress toward its target."""
    return render(
        request, "goals/goal_list.html", {"summaries": summarise(Goal.objects.all())}
    )


@login_required
def goal_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
    """A Goal, its Allocations and what's unallocated on each source."""
    goal = get_object_or_404(Goal, pk=pk)
    return render(request, "goals/goal_detail.html", {"summary": summarise([goal])[0]})


def _goal_form(request: HttpRequest, goal: Goal) -> HttpResponseBase:
    form = GoalForm(request.POST or None, instance=goal)
    if form.is_valid() and save_unique_name(
        form, "A Goal with this name already exists."
    ):
        messages.success(request, f"Saved {form.instance}.")
        return redirect("goal_detail", pk=form.instance.pk)
    return render(
        request,
        "goals/goal_form.html",
        {"form": form, "goal": goal if goal.pk else None},
    )


@login_required
def goal_create(request: HttpRequest) -> HttpResponseBase:
    """Create a Goal."""
    return _goal_form(request, Goal())


@login_required
@blocked_in_privacy_mode
def goal_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Change a Goal's name, target or date."""
    return _goal_form(request, get_object_or_404(Goal, pk=pk))


@login_required
def goal_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Delete a Goal and its Allocations; nothing else changes."""
    goal = get_object_or_404(Goal, pk=pk)
    if request.method == "POST":
        goal.delete()
        messages.success(request, f"Deleted {goal}.")
        return redirect("goal_list")
    return render(
        request,
        "confirm_delete.html",
        {"object": goal, "noun": "Goal", "list_url": reverse("goal_list")},
    )


def _allocation_form(
    request: HttpRequest, goal: Goal, allocation: Allocation
) -> HttpResponseBase:
    form = AllocationForm(request.POST or None, instance=allocation, goal=goal)
    if form.is_valid():
        saved = form.save()
        messages.success(request, f"Saved the Allocation of {saved.source_label}.")
        return redirect("goal_detail", pk=goal.pk)
    return render(
        request,
        "goals/allocation_form.html",
        {
            "form": form,
            "goal": goal,
            "allocation": allocation if allocation.pk else None,
        },
    )


@login_required
def allocation_create(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Allocate part of an Asset Account or Holding to the Goal."""
    return _allocation_form(request, get_object_or_404(Goal, pk=pk), Allocation())


@login_required
@blocked_in_privacy_mode
def allocation_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Change an Allocation's source or share."""
    allocation = get_object_or_404(
        Allocation.objects.select_related("goal", "account", "instrument"), pk=pk
    )
    return _allocation_form(request, allocation.goal, allocation)


@login_required
@require_POST
def allocation_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Remove an Allocation from its Goal."""
    allocation = get_object_or_404(
        Allocation.objects.select_related("account", "instrument"), pk=pk
    )
    allocation.delete()
    messages.success(request, f"Removed the Allocation of {allocation.source_label}.")
    return redirect("goal_detail", pk=allocation.goal_id)
