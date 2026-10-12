"""What the Party and Tag pages share: tabs, sorting, the chart and actions."""

from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.db.models import F, OrderBy
from django.db.models.functions import Greatest, Lower
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.activity import MONTHS, bars
from apps.classification.models import Party, Tag
from apps.core.dates import months_after
from apps.core.forms import MergeForm

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from apps.accounts.activity import Bar
    from apps.classification.activity import Activity
    from apps.users.models import User

SORTS: dict[str, list[OrderBy]] = {
    "name": [],
    "amount": [Greatest("spent", "earned").desc()],
    "recent": [F("last_used").desc(nulls_last=True)],
}
SORT_LABELS = (("name", "Name"), ("amount", "Amount"), ("recent", "Recent"))
DETAIL = {"party": "party_transactions", "tag": "tag_transactions"}


def sort_from(request: HttpRequest) -> str:
    """The sort the request asks for, else by name."""
    sort = request.GET.get("sort", "")
    return sort if sort in SORTS else "name"


def ordering(sort: str) -> list[OrderBy | Lower]:
    """How to order a list by the sort, ties broken by name."""
    return [*SORTS[sort], Lower("name")]


def today() -> date:
    """Today, in the user's time zone."""
    return timezone.localdate()


def year_start() -> date:
    """The first day of the last MONTHS months, this one included."""
    return months_after(today().replace(day=1), 1 - MONTHS)


def tabs(current: str) -> list[dict[str, object]]:
    """Parties and Tags with their visible counts, for switching between lists."""
    return [
        {
            "title": title,
            "count": model.objects.filter(hidden=False).count(),
            "url": reverse(f"{noun}_list"),
            "active": noun == current,
        }
        for noun, title, model in (("party", "Parties", Party), ("tag", "Tags", Tag))
    ]


def chart(request: HttpRequest, result: Activity) -> list[Bar]:
    """The month bars, or none in Privacy Mode."""
    if cast("User", request.user).privacy_mode:
        return []
    starts, totals = zip(*result.months, strict=True)
    return bars(starts, totals)


def saved(request: HttpRequest, obj: Party | Tag, *, editing: bool) -> None:
    """Say the Party or Tag was saved."""
    messages.success(request, f"Saved {obj}." if editing else f"Added {obj}.")


def set_hidden(
    request: HttpRequest, obj: Party | Tag, noun: str, *, hidden: bool
) -> HttpResponseBase:
    """Hide or unhide, then return to its page."""
    obj.hidden = hidden
    obj.save()
    messages.success(
        request,
        f"Hid {obj}. It keeps its Transactions."
        if hidden
        else f"{obj} is back in the list.",
    )
    return redirect(DETAIL[noun], pk=obj.pk)


def merge_page[R: (Party, Tag)](
    request: HttpRequest,
    source: R,
    merge: Callable[[R, R], None],
    noun: str,
    impact: str,
) -> HttpResponseBase:
    """Choose a target, then Merge the source into it and go to the target."""
    targets = type(source).objects.exclude(pk=source.pk).order_by(Lower("name"))
    form = MergeForm(targets, request.POST or None)
    if form.is_valid():
        target = form.cleaned_data["target"]
        merge(source, target)
        messages.success(request, f"Merged {source} into {target}.")
        return redirect(DETAIL[noun], pk=target.pk)
    return render(
        request,
        "merge.html",
        {
            "object": source,
            "noun": noun,
            "form": form,
            "impact": [impact],
            "list_url": reverse(DETAIL[noun], args=[source.pk]),
        },
    )
