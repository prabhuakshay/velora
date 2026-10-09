"""Views for writing Quick Adds and reviewing their Drafts."""

from functools import wraps
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.quick_add import openrouter
from apps.quick_add.forms import QuickAddForm
from apps.quick_add.models import DraftSplit, QuickAdd
from apps.quick_add.tasks import process_quick_add

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase


def requires_quick_add[**P](
    view: Callable[P, HttpResponseBase],
) -> Callable[P, HttpResponseBase]:
    """Hide the view behind a 404 while AI Quick Add is off."""

    @wraps(view)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> HttpResponseBase:
        if not openrouter.is_configured():
            raise Http404
        return view(*args, **kwargs)

    return wrapper


@login_required
@requires_quick_add
@require_POST
def quick_add_create(request: HttpRequest) -> HttpResponseBase:
    """Save the Quick Add as processing and queue it for the AI."""
    form = QuickAddForm(request.POST)
    if not form.is_valid():
        for error in form["text"].errors:
            messages.error(request, str(error))
        return redirect("transaction_list")
    quick_add = form.save()
    # Same database transaction as the save, so the job never sees a missing row.
    process_quick_add.defer(quick_add_id=quick_add.pk)
    return redirect("draft_list")


@login_required
@requires_quick_add
def draft_list(request: HttpRequest) -> HttpResponseBase:
    """The Quick Adds that still need the user, with their Drafts."""
    quick_adds = list(
        QuickAdd.objects.on_drafts_page().prefetch_related(
            "draft__party",
            Prefetch(
                "draft__splits",
                queryset=DraftSplit.objects.select_related(
                    "from_account", "to_account"
                ),
            ),
        )
    )
    return render(
        request,
        "quick_add/draft_list.html",
        {
            "quick_adds": quick_adds,
            "processing": any(
                quick_add.status == QuickAdd.Status.PROCESSING
                for quick_add in quick_adds
            ),
        },
    )
