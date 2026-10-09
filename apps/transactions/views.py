"""Views for recording and reviewing Transactions."""

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Prefetch, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.transactions.forms import SplitFormSet, TransactionForm
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

PAGE_SIZE = 25


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
        .annotate(total=Sum("splits__amount"))
        .order_by("-date", "-pk")
    )
    page = Paginator(transactions, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "transactions/transaction_list.html", {"page": page})


def _edit(request: HttpRequest, instance: Transaction) -> HttpResponseBase:
    form = TransactionForm(request.POST or None, instance=instance)
    formset = SplitFormSet(request.POST or None, instance=instance)
    # Validate both so errors show on the Transaction and its Split at once.
    valid = all([form.is_valid(), formset.is_valid()])
    if valid and form.check_opening_balances(split.instance for split in formset):
        with db_transaction.atomic():
            formset.instance = form.save()
            formset.save()
        return redirect("transaction_list")
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
    return _edit(request, Transaction())


@login_required
def transaction_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a Transaction and its Split."""
    return _edit(request, get_object_or_404(Transaction, pk=pk))


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
