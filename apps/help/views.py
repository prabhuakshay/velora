"""The Help index and one Help page per area of Velora."""

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

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
