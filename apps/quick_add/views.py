"""Views for writing Quick Adds and reviewing Drafts."""

from functools import wraps
from typing import TYPE_CHECKING, Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.quick_add import openrouter
from apps.quick_add.forms import (
    DraftEditForm,
    DraftForm,
    DraftSplitFormSet,
    QuickAddForm,
)
from apps.quick_add.models import Draft, DraftSplit, QuickAdd
from apps.quick_add.posting import (
    DraftNotPostableError,
    matching_party,
    post_draft,
    post_edited,
    posting_problems,
    split_tags,
)
from apps.quick_add.stats import ai_stats
from apps.quick_add.tasks import process_quick_add

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.forms import BaseInlineFormSet
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


SECTION_HEADINGS = {
    Draft.Source.QUICK_ADD: "From Quick Add",
    Draft.Source.SCHEDULE: "From Schedules",
    Draft.Source.MANUAL: "Started by hand",
    Draft.Source.STATEMENT: "Card payments",
}


def waiting_draft(pk: int) -> Draft:
    """The waiting Draft, locked for the request's transaction, or a 404."""
    return get_object_or_404(
        Draft.objects.select_for_update(), pk=pk, status=Draft.Status.WAITING
    )


@login_required
def draft_list(request: HttpRequest) -> HttpResponseBase:
    """The waiting Drafts, and the Quick Adds still processing or failed."""
    drafts = list(
        Draft.objects.waiting()
        .select_related("party", "quick_add")
        .prefetch_related(
            Prefetch(
                "splits",
                queryset=DraftSplit.objects.select_related(
                    "from_account", "to_account"
                ),
            ),
        )
    )
    sections = [
        (heading, [draft for draft in drafts if draft.source == source])
        for source, heading in SECTION_HEADINGS.items()
    ]
    enabled = openrouter.is_configured()
    quick_adds = list(QuickAdd.objects.unfinished()) if enabled else []
    return render(
        request,
        "quick_add/draft_list.html",
        {
            "sections": [section for section in sections if section[1]],
            "quick_adds": quick_adds,
            "processing": any(quick_add.is_processing for quick_add in quick_adds),
            "stats": ai_stats() if enabled else None,
        },
    )


@login_required
def draft_create(request: HttpRequest) -> HttpResponseBase:
    """Start a Draft by hand, as a placeholder to finish later."""
    form = DraftForm(request.POST or None)
    if form.is_valid():
        form.instance.source = Draft.Source.MANUAL
        form.save()
        return redirect("draft_list")
    return render(request, "quick_add/draft_form.html", {"form": form})


@login_required
@require_POST
def draft_post(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Record the Draft as a Transaction, unchanged, or keep why it can't be."""
    # Locked for the request's transaction, so a double click posts once.
    draft = waiting_draft(pk)
    try:
        post_draft(draft)
    except DraftNotPostableError as error:
        draft.posting_error = str(error)
        draft.save(update_fields=["posting_error"])
    return redirect("draft_list")


def save_edits(
    draft: Draft, form: DraftEditForm, formset: BaseInlineFormSet[Any, Any, Any]
) -> bool:
    """Save the edits onto the Draft, unless it stopped waiting meanwhile."""
    with db_transaction.atomic():
        if not Draft.objects.select_for_update().filter(
            pk=draft.pk, status=Draft.Status.WAITING
        ):
            return False
        form.instance.posting_error = ""
        form.save()
        formset.save()
    return True


def render_draft_edit(
    request: HttpRequest,
    form: DraftEditForm,
    formset: BaseInlineFormSet[Any, Any, Any],
    posting_error: str = "",
) -> HttpResponseBase:
    """The Draft edit page."""
    return render(
        request,
        "transactions/transaction_form.html",
        {
            "form": form,
            "formset": formset,
            "new_party": form,
            "editing_draft": True,
            "posting_error": posting_error,
        },
    )


def unsaved_edit(
    draft: Draft,
) -> tuple[DraftEditForm, BaseInlineFormSet[Any, Any, Any], str]:
    """The edit forms filled from the Draft, and why it can't be posted yet."""
    party = matching_party(draft)
    problems = posting_problems(draft)
    return (
        DraftEditForm(
            instance=draft,
            initial={"party": party.pk, "new_party_name": ""} if party else {},
        ),
        DraftSplitFormSet(instance=draft),
        f"Can't post yet: {' '.join(problems)}" if problems else "",
    )


# TransactionForms.save must be the real commit, so a failed commit is seen
# there and the new files can be removed.
@db_transaction.non_atomic_requests
@login_required
def draft_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit the Draft, then save it as it is or save it and post it."""
    draft = get_object_or_404(Draft, pk=pk, status=Draft.Status.WAITING)
    if request.method != "POST":
        return render_draft_edit(request, *unsaved_edit(draft))
    form = DraftEditForm(request.POST, request.FILES, instance=draft)
    formset = DraftSplitFormSet(request.POST, instance=draft)
    if not (form.is_valid() and formset.is_valid()):
        return render_draft_edit(request, form, formset)
    if (
        save_edits(draft, form, formset)
        and request.POST.get("action") == "post"
        and (reasons := post_edited(draft, split_tags(formset), request.FILES))
    ):
        draft.posting_error = " ".join(reasons)
        draft.save(update_fields=["posting_error"])
        # Shown afresh from the saved Draft, so saving again can't add its new
        # Splits twice.
        return render_draft_edit(
            request,
            DraftEditForm(instance=draft),
            DraftSplitFormSet(instance=draft),
            f"Couldn't post: {draft.posting_error}",
        )
    return redirect("draft_list")


@login_required
@require_POST
def draft_reject(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Drop the Draft; it is kept, marked rejected, with its Quick Add if any."""
    waiting_draft(pk).reject()
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
    quick_add.save(update_fields=["status", "failure_reason"])
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
    failed_quick_add(pk).reject()
    return redirect("draft_list")


@login_required
@requires_quick_add
@require_POST
def quick_add_resubmit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Queue a Failed Quick Add again with its text edited."""
    form = QuickAddForm(request.POST, instance=failed_quick_add(pk))
    if form.is_valid():
        queue_again(form.save())
    else:
        show_errors(request, form)
    return redirect("draft_list")
