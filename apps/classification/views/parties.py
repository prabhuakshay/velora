"""Views for managing Parties."""

from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.classification.activity import activity
from apps.classification.forms import PartyForm
from apps.classification.merge import merge_party
from apps.classification.models import Party
from apps.classification.views.common import (
    SORT_LABELS,
    chart,
    merge_page,
    ordering,
    saved,
    set_hidden,
    sort_from,
    tabs,
    today,
    year_start,
)
from apps.core.views import paginate, redirect_in_use_to_merge, save_unique_name
from apps.transactions.models import Split

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


@login_required
def party_list(request: HttpRequest) -> HttpResponse:
    """List Parties with what was spent with or earned from each lately.

    Hidden ones are listed apart, folded away.
    """
    sort = sort_from(request)
    listed = list(Party.objects.with_usage(year_start()).order_by(*ordering(sort)))
    shown = [party for party in listed if not party.hidden]
    return render(
        request,
        "classification/party_list.html",
        {
            "tabs": tabs("party"),
            "parties": shown,
            "hidden": [party for party in listed if party.hidden],
            "spent": sum((p.spent for p in shown), Decimal(0)),
            "earned": sum((p.earned for p in shown), Decimal(0)),
            # What each Party's bar is a share of: the spending only.
            "share_of": sum((p.spent for p in shown if p.spent > 0), Decimal(0)),
            "unused": sum(1 for p in shown if not p.transaction_count),
            "sort": sort,
            "sorts": SORT_LABELS,
        },
    )


def _used_by(party: Party) -> str:
    """What keeps the Party from being deleted, or empty when nothing does."""
    return (
        "Transactions"
        if party.transactions.exists()
        else "Drafts"
        if party.drafts.exists()
        else "Schedules"
        if party.schedules.exists()
        else ""
    )


@login_required
def party_transactions(request: HttpRequest, pk: int) -> HttpResponse:
    """A Party's money all time and by month, and its Transactions, newest first."""
    party = get_object_or_404(Party, pk=pk)
    now = today()
    result = activity(Split.objects.filter(transaction__party=party), now)
    transactions = (
        party.transactions.prefetch_related(
            Prefetch(
                "splits",
                queryset=Split.objects.select_related("from_account", "to_account"),
            )
        )
        .annotate(total=Sum("splits__amount"))
        .order_by("-date", "-pk")
    )
    return render(
        request,
        "classification/party_detail.html",
        {
            "party": party,
            "activity": result,
            "bars": chart(request, result),
            "page": paginate(request, transactions),
            "schedules": [
                (schedule, schedule.has_ended(now))
                for schedule in party.schedules.order_by("-active", "pk")
            ],
            "used_by": _used_by(party),
            "here": request.get_full_path(),
        },
    )


@login_required
def party_create(request: HttpRequest) -> HttpResponseBase:
    """Create a party."""
    form = PartyForm(request.POST or None)
    if form.is_valid() and save_unique_name(form):
        saved(request, form.instance, editing=False)
        return redirect("party_transactions", pk=form.instance.pk)
    return render(request, "classification/party_form.html", {"form": form})


@login_required
def party_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a party."""
    party = get_object_or_404(Party, pk=pk)
    form = PartyForm(request.POST or None, instance=party)
    if form.is_valid() and save_unique_name(form):
        saved(request, party, editing=True)
        return redirect("party_transactions", pk=pk)
    return render(
        request, "classification/party_form.html", {"form": form, "party": party}
    )


@login_required
@require_POST
def party_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Hide a party from the list and from new Transactions."""
    party = get_object_or_404(Party, pk=pk)
    return set_hidden(request, party, "party", hidden=True)


@login_required
@require_POST
def party_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden party in the list again."""
    party = get_object_or_404(Party, pk=pk)
    return set_hidden(request, party, "party", hidden=False)


@login_required
def party_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a party."""
    party = get_object_or_404(Party, pk=pk)
    if used_by := _used_by(party):
        merge_url = reverse("party_merge", args=[party.pk])
        return redirect_in_use_to_merge(
            request, party, "party", merge_url, used_by=used_by
        )
    if request.method == "POST":
        party.delete()
        messages.success(request, f"Deleted {party}.")
        return redirect("party_list")
    return render(
        request,
        "confirm_delete.html",
        {
            "object": party,
            "noun": "party",
            "list_url": reverse("party_transactions", args=[pk]),
        },
    )


@login_required
def party_merge(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Choose a target, then Merge a party into it."""
    party = get_object_or_404(Party, pk=pk)
    count = party.transactions.count()
    schedules = party.schedules.count()
    impact = (
        f"{count} Transaction{pluralize(count)} and "
        f"{schedules} Schedule{pluralize(schedules)} will move."
    )
    return merge_page(request, party, merge_party, "party", impact)
