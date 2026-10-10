"""Views for managing Accounts, one set shared by every kind."""

from datetime import date
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.forms import AccountForm
from apps.accounts.merge import AccountMerge
from apps.accounts.models import BALANCE_KINDS, Account
from apps.accounts.net_worth import net_worth, net_worth_history
from apps.core.forms import MergeForm
from apps.core.views import (
    paginate,
    redirect_in_use_to_merge,
    save_unique_name,
    set_hidden,
)
from apps.transactions.models import Split, Transaction
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from decimal import Decimal

    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

CHART_WIDTH = 600
CHART_HEIGHT = 200
STATEMENTS_SHOWN = 6


def _as_of_date(raw: str | None) -> date:
    """The as-of date from a GET value; today when missing, invalid or future."""
    today = timezone.localdate()
    try:
        when = date.fromisoformat(raw or "")
    except ValueError:
        return today
    return min(when, today)


def _chart_points(values: list[Decimal]) -> str:
    """SVG polyline points scaling the values to fill the chart; flat mid-height."""
    if not values:
        return ""
    low, high = min(values), max(values)
    if len(values) == 1:
        values = values * 2
    step = CHART_WIDTH / (len(values) - 1)

    def y(value: Decimal) -> float:
        if high == low:
            return CHART_HEIGHT / 2
        return float(CHART_HEIGHT - (value - low) / (high - low) * CHART_HEIGHT)

    return " ".join(f"{step * i:.1f},{y(value):.1f}" for i, value in enumerate(values))


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Show Net Worth with the Assets and Liabilities totals behind it."""
    as_of = _as_of_date(request.GET.get("as_of"))
    today = timezone.localdate()
    history = net_worth_history(today)
    return render(
        request,
        "index.html",
        {
            "as_of": as_of,
            "today": today,
            "net_worth": net_worth(as_of),
            "history": history,
            "chart": {
                "width": CHART_WIDTH,
                "height": CHART_HEIGHT,
                "points": _chart_points([value for _, value in history]),
            },
        },
    )


@login_required
def account_list(request: HttpRequest, kind: str) -> HttpResponse:
    """List one kind's Accounts by name, a page at a time."""
    show_hidden = request.GET.get("show_hidden") == "1"
    accounts = Account.objects.filter(kind=kind).order_by(Lower("name"))
    if not show_hidden:
        accounts = accounts.filter(hidden=False)
    if kind in BALANCE_KINDS:
        accounts = accounts.with_balance()
    return render(
        request,
        "accounts/account_list.html",
        {
            "page": paginate(request, accounts),
            "kind": Account.Kind(kind),
            "show_hidden": show_hidden,
        },
    )


@login_required
def account_transactions(request: HttpRequest, kind: str, pk: int) -> HttpResponse:
    """List the Transactions touching an Account, newest first, a page at a time."""
    accounts = Account.objects.filter(kind=kind)
    if kind in BALANCE_KINDS:
        accounts = accounts.with_balance()
    account = get_object_or_404(accounts, pk=pk)
    today = timezone.localdate()
    touching = Split.objects.filter(Q(from_account=account) | Q(to_account=account))
    transactions = (
        Transaction.objects.filter(pk__in=touching.values("transaction"))
        .select_related("party")
        .prefetch_related(
            Prefetch(
                "splits",
                queryset=touching.select_related("from_account", "to_account"),
            )
        )
        .order_by("-date", "-pk")
    )
    return render(
        request,
        "accounts/account_transactions.html",
        {
            "account": account,
            "kind": Account.Kind(kind),
            "page": paginate(request, transactions),
            "statements": account.statements.order_by("-period_end")[:STATEMENTS_SHOWN],
            "card_emis": [
                (emi, emi.progress(today))
                for emi in account.card_emis.select_related("card", "purchase")
            ],
            # Purchases off the card that can still become a Card EMI.
            "emi_candidates": set(
                touching.filter(
                    from_account=account,
                    from_account__statement_day__isnull=False,
                    transaction__card_emi__isnull=True,
                ).values_list("transaction", flat=True)
            ),
        },
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
@blocked_in_privacy_mode
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
    used_by = (
        "Transactions"
        if account.splits_out.exists() or account.splits_in.exists()
        else "a credit card it pays"
        if account.cards_paid.exists()
        else ""
    )
    if used_by:
        noun = f"{Account.Kind(kind).label} Account"
        merge_url = reverse("account_merge", kwargs={"kind": kind, "pk": pk})
        return redirect_in_use_to_merge(
            request, account, noun, merge_url, used_by=used_by
        )
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
        if request.method == "POST" and not merge.refusal:
            merge.run()
            messages.success(request, f"Merged {source} into {merge.target}.")
            return redirect("account_list", kind=kind)
    return render(
        request,
        "accounts/account_merge.html",
        {"form": form, "kind": Account.Kind(kind), "source": source, "merge": merge},
    )
