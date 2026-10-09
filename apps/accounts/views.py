"""Views for managing Accounts, one set shared by every kind."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, F, OuterRef, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.forms import AccountForm, AccountMergeForm
from apps.accounts.merge import AccountMerge
from apps.accounts.models import BALANCE_KINDS, Account
from apps.core.views import save_unique_name, set_hidden
from apps.transactions.models import Split

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _split_total(account_field: str) -> Coalesce:
    totals = (
        Split.objects.filter(**{account_field: OuterRef("pk")})
        .values(account_field)
        .annotate(total=Sum("amount"))
        .values("total")
    )
    money = DecimalField(max_digits=15, decimal_places=2)
    return Coalesce(Subquery(totals), Value(0), output_field=money)


def with_balance(accounts: QuerySet[Account], kind: str) -> QuerySet[Account]:
    """Annotate each Account's Balance; a Liability's reads as what is owed."""
    moved_in = _split_total("to_account") - _split_total("from_account")
    if kind == Account.Kind.LIABILITY:
        moved_in = -moved_in
    return accounts.annotate(balance=F("opening_balance") + moved_in)


@login_required
def account_list(request: HttpRequest, kind: str) -> HttpResponse:
    """List one kind's Accounts by name."""
    show_hidden = request.GET.get("show_hidden") == "1"
    accounts = Account.objects.filter(kind=kind).order_by(Lower("name"))
    if not show_hidden:
        accounts = accounts.filter(hidden=False)
    if kind in BALANCE_KINDS:
        accounts = with_balance(accounts, kind)
    return render(
        request,
        "accounts/account_list.html",
        {"accounts": accounts, "kind": Account.Kind(kind), "show_hidden": show_hidden},
    )


@login_required
def account_create(request: HttpRequest, kind: str) -> HttpResponseBase:
    """Create an Account of the kind in the URL."""
    form = AccountForm(request.POST or None, instance=Account(kind=kind))
    if form.is_valid() and save_unique_name(form, form.duplicate_name_error):
        return redirect("account_list", kind=kind)
    return render(
        request,
        "accounts/account_form.html",
        {"form": form, "kind": Account.Kind(kind)},
    )


@login_required
def account_edit(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Edit an Account, which must be of the kind in the URL."""
    account = get_object_or_404(Account, pk=pk, kind=kind)
    form = AccountForm(request.POST or None, instance=account)
    if form.is_valid() and save_unique_name(form, form.duplicate_name_error):
        return redirect("account_list", kind=kind)
    return render(
        request,
        "accounts/account_form.html",
        {"form": form, "kind": Account.Kind(kind), "account": account},
    )


@login_required
@require_POST
def account_hide(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Hide an Account from its kind's default list."""
    account = get_object_or_404(Account, pk=pk, kind=kind)
    list_url = reverse("account_list", kwargs={"kind": kind})
    return set_hidden(request, account, list_url, hidden=True)


@login_required
@require_POST
def account_unhide(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Show a hidden Account in its kind's default list again."""
    account = get_object_or_404(Account, pk=pk, kind=kind)
    list_url = reverse("account_list", kwargs={"kind": kind})
    return set_hidden(request, account, list_url, hidden=False)


@login_required
def account_delete(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Confirm, then delete an Account of the kind in the URL."""
    account = get_object_or_404(Account, pk=pk, kind=kind)
    if account.splits_out.exists() or account.splits_in.exists():
        label = Account.Kind(kind).label
        messages.info(
            request,
            f"{account} is used by Transactions, so it cannot be deleted. "
            f"Merge it into another {label} Account, or hide it instead.",
        )
        return redirect("account_merge", kind=kind, pk=pk)
    if request.method == "POST":
        account.delete()
        return redirect("account_list", kind=kind)
    return render(
        request,
        "confirm_delete.html",
        {
            "object": account,
            "noun": f"{Account.Kind(kind).label} Account",
            "list_url": reverse("account_list", kwargs={"kind": kind}),
        },
    )


@login_required
def account_merge(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Choose a target and see the impact, then Merge the Account into it."""
    source = get_object_or_404(Account, pk=pk, kind=kind)
    form = AccountMergeForm(source, request.POST or request.GET or None)
    merge = None
    if form.is_valid():
        merge = AccountMerge(source, form.cleaned_data["target"])
        if request.method == "POST":
            merge.run()
            messages.success(request, f"Merged {source} into {merge.target}.")
            return redirect("account_list", kind=kind)
    return render(
        request,
        "accounts/account_merge.html",
        {"form": form, "kind": Account.Kind(kind), "source": source, "merge": merge},
    )
