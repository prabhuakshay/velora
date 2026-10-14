"""The Help index and one Help page per area of Velora."""

from typing import TYPE_CHECKING, cast

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.users.models import User

# Slug to title, in the order the Help index lists them.
AREAS = {
    "transactions": "Transactions",
    "drafts": "Drafts and Quick Add",
    "schedules": "Schedules and Subscriptions",
    "forecast": "Forecast",
    "budgets": "Budgets",
    "accounts": "Accounts and Reconciliation",
    "cards": "Cards",
    "investments": "Investments",
    "goals": "Goals",
    "classification": "Classification",
}


@login_required
def help_index(request: HttpRequest) -> HttpResponse:
    """Getting started, then a link to every area's Help page."""
    return render(request, "help/index.html", {"areas": AREAS})


@login_required
def help_area(request: HttpRequest, slug: str) -> HttpResponse:
    """One area's Help page."""
    if slug not in AREAS:
        raise Http404
    return render(request, f"help/{slug}.html", {"title": AREAS[slug]})


@login_required
@require_POST
def tour_seen(request: HttpRequest, tour: str) -> HttpResponse:
    """Remember the user has been shown the page's guided tour."""
    cast("User", request.user).see_tour(tour)
    return HttpResponse(status=204)
