"""Views for an Account's Reconciliations: recording, listing and deleting them."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.activity import rows, touching_transactions
from apps.accounts.forms import ReconcileForm
from apps.accounts.models import BALANCE_KINDS, Account, Reconciliation
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def reconciliation_status(account: Account, shown: int) -> dict[str, object]:
    """Its latest Reconciliations, how many, the latest if off, the latest matching."""
    latest = list(account.reconciliations.with_difference().order_by("-date")[:shown])
    return {
        "reconciliations": latest,
        "reconciliation_count": account.reconciliations.count(),
        "latest_off": latest[0] if latest and latest[0].difference else None,
        "reconciled_through": account.reconciliations.matching()
        .order_by("-date")
        .first(),
    }


@login_required
@blocked_in_privacy_mode
def account_reconcile(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Record a Reconciliation if the bank's balance matches Velora's that day.

    On a mismatch, nothing is saved and the page shows the difference and the
    Transactions since the latest Reconciliation still matching, or the Opening
    Balance date.
    """
    accounts = Account.objects.filter(kind__in=BALANCE_KINDS).with_balance()
    account = get_object_or_404(accounts, pk=pk, kind=kind)
    form = ReconcileForm(request.POST or None, account=account)
    if form.is_valid():
        reconciliation = form.save()
        messages.success(
            request, f"Reconciled {account} on {reconciliation.date:%-d %b %Y}."
        )
        return redirect("account_transactions", kind=kind, pk=pk)
    context = {"account": account, "kind": Account.Kind(kind), "form": form}
    if form.difference:
        when = form.cleaned_data["date"]
        previous = (
            account.reconciliations.matching()
            .filter(date__lt=when)
            .order_by("-date")
            .first()
        )
        transactions = touching_transactions(account).filter(date__lte=when)
        if previous:
            transactions = transactions.filter(date__gt=previous.date)
        else:
            transactions = transactions.filter(date__gte=account.opening_balance_date)
        context |= {
            "difference": form.difference,
            "velora_balance": account.balance_on(when),
            "previous": previous,
            "rows": rows(account, list(transactions)),
        }
    return render(request, "accounts/reconcile.html", context)


@login_required
def reconciliation_history(request: HttpRequest, kind: str, pk: int) -> HttpResponse:
    """Every Reconciliation of the Account, newest first."""
    account = get_object_or_404(Account, pk=pk, kind=kind)
    return render(
        request,
        "accounts/reconciliation_history.html",
        {
            "account": account,
            "kind": Account.Kind(kind),
            "reconciliations": account.reconciliations.with_difference().order_by(
                "-date"
            ),
        },
    )


@login_required
def reconciliation_delete(
    request: HttpRequest, kind: str, pk: int, reconciliation_pk: int
) -> HttpResponseBase:
    """Confirm, then delete one of the Account's Reconciliations.

    Returns to the full history when deleted from there, else to the Account.
    """
    reconciliation = get_object_or_404(
        Reconciliation, pk=reconciliation_pk, account__pk=pk, account__kind=kind
    )
    back = (
        "reconciliation_history"
        if request.GET.get("from") == "history"
        else "account_transactions"
    )
    label = f"Reconciliation on {reconciliation.date:%-d %b %Y}"
    if request.method == "POST":
        reconciliation.delete()
        messages.success(request, f"Deleted the {label}.")
        return redirect(back, kind=kind, pk=pk)
    return render(
        request,
        "confirm_delete.html",
        {
            "object": label,
            "noun": "Reconciliation",
            "list_url": reverse(back, kwargs={"kind": kind, "pk": pk}),
        },
    )
