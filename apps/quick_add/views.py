"""Views for writing Quick Adds and reviewing their Drafts."""

from contextlib import suppress
from functools import wraps
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.quick_add import openrouter
from apps.quick_add.forms import NewPartyForm, QuickAddForm
from apps.quick_add.models import DraftSplit, QuickAdd
from apps.quick_add.posting import (
    DraftGoneError,
    DraftNotPostableError,
    form_data,
    matching_party,
    post_draft,
    posting_edited,
)
from apps.quick_add.stats import ai_stats
from apps.quick_add.tasks import process_quick_add
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms

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


def show_errors(request: HttpRequest, form: QuickAddForm) -> None:
    """Flash why the Quick Add text was refused."""
    for error in form["text"].errors:
        messages.error(request, str(error))


@login_required
@requires_quick_add
@require_POST
def quick_add_create(request: HttpRequest) -> HttpResponseBase:
    """Save the Quick Add as processing and queue it for the AI."""
    form = QuickAddForm(request.POST)
    if not form.is_valid():
        show_errors(request, form)
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
            "stats": ai_stats(),
        },
    )


@login_required
@requires_quick_add
@require_POST
def draft_post(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Record the Draft as a Transaction, unchanged, or keep why it can't be."""
    # Locked for the request's transaction, so a double click posts once.
    quick_add = get_object_or_404(
        QuickAdd.objects.select_for_update(), pk=pk, status=QuickAdd.Status.DRAFT
    )
    try:
        post_draft(quick_add)
    except DraftNotPostableError as error:
        quick_add.failure_reason = str(error)
        quick_add.save(update_fields=["failure_reason"])
    return redirect("draft_list")


# TransactionForms.save must be the real commit, so a failed commit is seen
# there and the new files can be removed.
@db_transaction.non_atomic_requests
@login_required
@requires_quick_add
def draft_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """The Transaction form filled from the Draft; saving it posts the Draft."""
    quick_add = get_object_or_404(QuickAdd, pk=pk, status=QuickAdd.Status.DRAFT)
    draft = quick_add.draft
    if request.method == "POST":
        forms = TransactionForms(request.POST, request.FILES, instance=Transaction())
        new_party = NewPartyForm(request.POST)
        if forms.is_valid() and new_party.is_valid():
            posting = posting_edited(
                quick_add,
                forms.form.instance,
                new_party.cleaned_data["new_party_name"],
            )
            with suppress(DraftGoneError):
                forms.save(within=posting)
            return redirect("draft_list")
    else:
        party = matching_party(draft)
        # Bound, so a Draft that no longer passes shows why straight away.
        forms = TransactionForms(form_data(draft, party), instance=Transaction())
        forms.is_valid()
        new_party = NewPartyForm(
            initial={"new_party_name": "" if party else draft.new_party_name}
        )
    return render(
        request,
        "transactions/transaction_form.html",
        {"form": forms.form, "formset": forms.formset, "new_party": new_party},
    )


@login_required
@requires_quick_add
@require_POST
def draft_reject(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Drop the Draft; the Quick Add and Draft are kept, marked rejected."""
    quick_add = get_object_or_404(
        QuickAdd.objects.select_for_update(), pk=pk, status=QuickAdd.Status.DRAFT
    )
    quick_add.status = QuickAdd.Status.REJECTED
    quick_add.save(update_fields=["status"])
    return redirect("draft_list")


def failed_quick_add(pk: int) -> QuickAdd:
    """The Failed Quick Add, locked for the request's transaction, or a 404."""
    return get_object_or_404(
        QuickAdd.objects.select_for_update(), pk=pk, status=QuickAdd.Status.FAILED
    )


def queue_again(quick_add: QuickAdd) -> None:
    """Send the failed Quick Add back to the AI."""
    quick_add.status = QuickAdd.Status.PROCESSING
    quick_add.failure_reason = ""
    quick_add.save(update_fields=["text", "status", "failure_reason"])
    process_quick_add.defer(quick_add_id=quick_add.pk)


@login_required
@requires_quick_add
@require_POST
def quick_add_retry(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Queue a Failed Quick Add again as it is."""
    queue_again(failed_quick_add(pk))
    return redirect("draft_list")


@login_required
@requires_quick_add
@require_POST
def quick_add_discard(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Hide a Failed Quick Add from the Drafts page; it is kept, marked rejected."""
    quick_add = failed_quick_add(pk)
    quick_add.status = QuickAdd.Status.REJECTED
    quick_add.save(update_fields=["status"])
    return redirect("draft_list")


@login_required
@requires_quick_add
@require_POST
def quick_add_resubmit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Queue a Failed Quick Add again with its text edited."""
    form = QuickAddForm(request.POST, instance=failed_quick_add(pk))
    if form.is_valid():
        queue_again(form.instance)
    else:
        show_errors(request, form)
    return redirect("draft_list")
