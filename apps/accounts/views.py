"""Views for managing Accounts, one set shared by every kind."""

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.forms import AccountForm
from apps.accounts.models import Account
from apps.core.views import save_unique_name

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


@login_required
def account_list(request: HttpRequest, kind: str) -> HttpResponse:
    """List one kind's Accounts by name."""
    accounts = Account.objects.filter(kind=kind).order_by(Lower("name"))
    return render(
        request,
        "accounts/account_list.html",
        {"accounts": accounts, "kind": Account.Kind(kind)},
    )


@login_required
def account_create(request: HttpRequest, kind: str) -> HttpResponseBase:
    """Create an Account of the kind in the URL."""
    form = AccountForm(request.POST or None, instance=Account(kind=kind))
    if form.is_valid() and save_unique_name(form):
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
    if form.is_valid() and save_unique_name(form):
        return redirect("account_list", kind=kind)
    return render(
        request,
        "accounts/account_form.html",
        {"form": form, "kind": Account.Kind(kind), "account": account},
    )
