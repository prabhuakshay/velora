"""Views for recording and reviewing Transactions."""

from typing import TYPE_CHECKING, cast

from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Count, OuterRef, Prefetch, Subquery, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.core.views import paginate
from apps.transactions.attachments import save_attachments
from apps.transactions.forms import BaseSplitFormSet, SplitFormSet, TransactionForm
from apps.transactions.models import Attachment, Split, Transaction
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


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
    form = TransactionForm(
        request.POST or None, request.FILES or None, instance=instance
    )
    formset = cast(
        "BaseSplitFormSet", SplitFormSet(request.POST or None, instance=instance)
    )
    # Validate both so errors show on the Transaction and its Split at once.
    valid = all([form.is_valid(), formset.is_valid()])
    if valid and formset.check_opening_balances(form.cleaned_data["date"]):
        with db_transaction.atomic():
            formset.instance = form.save()
            formset.save()
            save_attachments(formset.instance, form.cleaned_data["attachments"])
        return redirect("transaction_list")
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


@login_required
def transaction_create(request: HttpRequest) -> HttpResponseBase:
    """Record a new Transaction."""
    return _save_transaction_forms(request, Transaction())


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
def transaction_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a Transaction and its Splits."""
    transaction = get_object_or_404(Transaction, pk=pk)
    if request.method == "POST":
        transaction.delete()
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
