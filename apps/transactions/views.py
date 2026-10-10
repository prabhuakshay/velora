"""Views for recording and reviewing Transactions."""

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Count, OuterRef, Prefetch, Subquery, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.views import paginate
from apps.transactions import cloudflare
from apps.transactions.attachments import (
    AttachmentDeleteError,
    delete_attachment_files,
)
from apps.transactions.forms import SplitFormSet
from apps.transactions.models import Attachment, Split, Transaction
from apps.transactions.recording import TransactionForms
from apps.transactions.storage_chart import StorageChart
from apps.transactions.storage_stats import attachment_storage_stats
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

logger = logging.getLogger(__name__)


@login_required
def transaction_list(request: HttpRequest) -> HttpResponse:
    """List every Transaction, newest first, a page at a time."""
    transactions = (
        Transaction.objects.select_related("party")
        .prefetch_related(
            Prefetch(
                "splits",
                queryset=Split.objects.select_related("from_account", "to_account"),
            )
        )
        .annotate(
            total=Sum("splits__amount"),
            # A subquery, as joining attachments would multiply the splits total.
            attachment_count=Subquery(
                Attachment.objects.filter(transaction=OuterRef("pk"))
                .values("transaction")
                .annotate(count=Count("pk"))
                .values("count")
            ),
        )
        .order_by("-date", "-pk")
    )
    page = paginate(request, transactions)
    return render(request, "transactions/transaction_list.html", {"page": page})


def _save_transaction_forms(
    request: HttpRequest, instance: Transaction
) -> HttpResponseBase:
    """Show the create or edit form, saving the Transaction and Splits once valid."""
    forms = TransactionForms(
        request.POST or None, request.FILES or None, instance=instance
    )
    if forms.is_valid():
        forms.save()
        return redirect("transaction_list")
    form, formset = forms.form, forms.formset
    if request.FILES:
        form.add_error(
            "attachments",
            "Your files weren't saved because of the errors. Pick them again.",
        )
    return render(
        request,
        "transactions/transaction_form.html",
        {
            "form": form,
            "formset": formset,
            "transaction": instance if instance.pk else None,
        },
    )


# TransactionForms.save must be the real commit, so a failed commit is seen
# there and the new files can be removed.
@db_transaction.non_atomic_requests
@login_required
def transaction_create(request: HttpRequest) -> HttpResponseBase:
    """Record a new Transaction."""
    return _save_transaction_forms(request, Transaction())


@db_transaction.non_atomic_requests
@login_required
@blocked_in_privacy_mode
def transaction_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a Transaction and its Splits."""
    return _save_transaction_forms(request, get_object_or_404(Transaction, pk=pk))


@login_required
def split_row(request: HttpRequest) -> HttpResponse:
    """A blank Split row for the form's "add split" control."""
    total = request.GET.get("splits-TOTAL_FORMS", "")
    index = int(total) if total.isdigit() else 0
    split = SplitFormSet().empty_form
    split.prefix = f"splits-{index}"
    return render(
        request,
        "transactions/split_row_added.html",
        {"split": split, "total": index + 1},
    )


@login_required
@blocked_in_privacy_mode
def attachment_open(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Send the browser to a short-lived storage link for the Attachment."""
    return redirect(get_object_or_404(Attachment, pk=pk).presigned_url())


@login_required
@require_POST
def attachment_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Delete an Attachment and its stored file, then return to its Transaction."""
    attachment = get_object_or_404(Attachment, pk=pk)
    try:
        with db_transaction.atomic():
            attachment.delete()
            delete_attachment_files([attachment])
    except AttachmentDeleteError as error:
        messages.error(request, str(error))
    return redirect("transaction_edit", pk=attachment.transaction_id)


@login_required
def transaction_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a Transaction, its Splits and its Attachments."""
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == "POST":
        try:
            with db_transaction.atomic():
                delete_attachment_files(transaction.attachments.all())
                transaction.delete()
        except AttachmentDeleteError as error:
            messages.error(request, str(error))
            return redirect("transaction_delete", pk=pk)
        return redirect("transaction_list")
    return render(
        request,
        "confirm_delete.html",
        {
            "object": transaction,
            "noun": "Transaction",
            "list_url": reverse("transaction_list"),
        },
    )


@login_required
def storage(request: HttpRequest) -> HttpResponse:
    """Attachment storage figures from Velora's own records."""
    return render(
        request,
        "transactions/storage.html",
        {
            "stats": attachment_storage_stats(),
            "analytics": cloudflare.is_configured(),
        },
    )


@login_required
def storage_analytics(request: HttpRequest) -> HttpResponse:
    """The Storage page's Cloudflare analytics section, loaded by htmx."""
    if not cloudflare.is_configured():
        raise Http404
    template = "transactions/_storage_analytics.html"
    try:
        days = cloudflare.daily_storage()
    except OSError, ValueError:
        logger.exception("Couldn't fetch Cloudflare storage analytics.")
        return render(request, template, {"failed": True})
    return render(request, template, {"chart": StorageChart.of(days)})
