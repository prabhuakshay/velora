"""Views for managing Accounts, one set shared by every kind."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.forms import AccountForm
from apps.accounts.merge import AccountMerge
from apps.accounts.models import BALANCE_KINDS, Account
from apps.accounts.net_worth import as_of_date, net_worth
from apps.core.forms import MergeForm
from apps.core.views import redirect_in_use_to_merge, save_unique_name, set_hidden

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Show Net Worth with the Assets and Liabilities totals behind it."""
    as_of = as_of_date(request.GET.get("as_of"))
    return render(
        request,
        "index.html",
        {
            "as_of": as_of,
            "today": timezone.localdate(),
            "net_worth": net_worth(as_of),
        },
    )


@login_required
def account_list(request: HttpRequest, kind: str) -> HttpResponse:
    """List one kind's Accounts by name."""
    show_hidden = request.GET.get("show_hidden") == "1"
    accounts = Account.objects.filter(kind=kind).order_by(Lower("name"))
    if not show_hidden:
        accounts = accounts.filter(hidden=False)
    if kind in BALANCE_KINDS:
        accounts = accounts.with_balance()
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
        noun = f"{Account.Kind(kind).label} Account"
        merge_url = reverse("account_merge", kwargs={"kind": kind, "pk": pk})
        return redirect_in_use_to_merge(request, account, noun, merge_url)
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
    targets = Account.objects.filter(kind=kind).exclude(pk=pk).order_by(Lower("name"))
    form = MergeForm(targets, request.POST or request.GET or None)
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
