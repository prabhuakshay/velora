"""Views for managing Accounts, one set shared by every kind."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Prefetch, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.activity import bars, month_end, months, rows
from apps.accounts.forecast import forecast
from apps.accounts.forms import AccountForm
from apps.accounts.merge import AccountMerge
from apps.accounts.models import BALANCE_KINDS, Account
from apps.accounts.net_worth import net_worth, net_worth_history
from apps.core.dates import months_after
from apps.core.forms import MergeForm
from apps.core.views import paginate, redirect_in_use_to_merge, save_unique_name
from apps.transactions.models import Split, Transaction
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

    from apps.users.models import User

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
    privacy_mode = cast("User", request.user).privacy_mode
    history = [] if privacy_mode else net_worth_history(today)
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
def forecast_page(request: HttpRequest) -> HttpResponse:
    """Each Account's expected Balance for the coming days, and its warnings."""
    result = forecast(timezone.localdate())
    days = [
        {
            "day": day,
            "balances": [row.balances[index] for row in result.accounts],
            "amountless": [item for item in result.amountless if item.when == day],
        }
        for index, day in enumerate(result.days)
    ]
    return render(
        request,
        "accounts/forecast.html",
        {"forecast": result, "days": days},
    )


KIND_TITLES = {
    Account.Kind.ASSET: "Assets",
    Account.Kind.LIABILITY: "Liabilities",
    Account.Kind.EXPENSE: "Expenses",
    Account.Kind.INCOME: "Income",
}
SORTS = ("name", "amount", "recent")


def _kind_tabs(current: str) -> list[dict[str, object]]:
    """Each kind with its visible Account count, for switching between lists."""
    counts = dict(
        Account.objects.filter(hidden=False)
        .values_list("kind")
        .annotate(count=Count("pk"))
        .values_list("kind", "count")
    )
    return [
        {
            "kind": kind,
            "title": title,
            "count": counts.get(kind, 0),
            "url": reverse("account_list", kwargs={"kind": kind}),
            "active": kind == current,
        }
        for kind, title in KIND_TITLES.items()
    ]


def _used_by(account: Account) -> str:
    """What keeps the Account from being deleted, or empty when nothing does."""
    return (
        "Transactions"
        if account.splits_out.exists() or account.splits_in.exists()
        else "a credit card it pays"
        if account.cards_paid.exists()
        else "a Card EMI's interest"
        if account.card_emi_interest.exists()
        else "Schedules"
        if account.schedule_splits_out.exists()
        or account.schedule_splits_in.exists()
        or account.suggested_schedules_out.exists()
        or account.suggested_schedules_in.exists()
        else ""
    )


@login_required
def account_list(request: HttpRequest, kind: str) -> HttpResponse:
    """List one kind's Accounts with how each stands and moved this month.

    Hidden ones are listed apart, folded away.
    """
    today = timezone.localdate()
    this_month = today.replace(day=1)
    last_month = months_after(this_month, -1)
    sort = request.GET.get("sort", "")
    sort = sort if sort in SORTS else SORTS[0]
    balances = kind in BALANCE_KINDS
    accounts = (
        Account.objects.filter(kind=kind)
        .with_activity("this_month", this_month, month_end(this_month))
        .with_activity("last_month", last_month, month_end(last_month))
        .with_last_used()
    )
    if balances:
        accounts = accounts.with_balance()
    by = {
        "name": [],
        "amount": [F("balance" if balances else "this_month").desc()],
        "recent": [F("last_used").desc(nulls_last=True)],
    }[sort]
    listed = list(accounts.order_by(*by, Lower("name")))
    shown = [account for account in listed if not account.hidden]
    return render(
        request,
        "accounts/account_list.html",
        {
            "kind": Account.Kind(kind),
            "title": KIND_TITLES[Account.Kind(kind)],
            "tabs": _kind_tabs(kind),
            "accounts": shown,
            "hidden": [account for account in listed if account.hidden],
            "balances": balances,
            "total": sum(
                (a.balance if balances else a.this_month for a in shown), Decimal(0)
            ),
            "this_month_total": sum((a.this_month for a in shown), Decimal(0)),
            # What each Account's bar is a share of: the month's gains only.
            "share_of": sum(
                (a.this_month for a in shown if a.this_month > 0), Decimal(0)
            ),
            "last_month_total": sum((a.last_month for a in shown), Decimal(0)),
            "cards": sum(1 for a in shown if a.is_card),
            "sort": sort,
            "sorts": [
                ("name", "Name"),
                ("amount", "Balance" if balances else "This month"),
                ("recent", "Recent"),
            ],
            "today": today,
            "last_month": last_month,
        },
    )


def _account_forecast(account: Account) -> dict[str, object] | None:
    """Where the Forecast expects the Account in 30 days, and its low point."""
    if not account.has_opening_balance or account.hidden:
        return None
    result = forecast(timezone.localdate())
    row = next((r for r in result.accounts if r.account.pk == account.pk), None)
    if row is None:
        return None
    owes = account.kind == Account.Kind.LIABILITY
    worst = (max if owes else min)(
        zip(result.days, row.balances, strict=True), key=lambda pair: pair[1]
    )
    return {
        "end": row.balances[-1],
        "end_day": result.days[-1],
        "worst": worst[1],
        "worst_day": worst[0],
        "breach": next(
            (b for b in result.breaches if b.account.pk == account.pk), None
        ),
    }


@login_required
def account_transactions(request: HttpRequest, kind: str, pk: int) -> HttpResponse:
    """An Account's standing, its months and its Transactions, newest first."""
    accounts = Account.objects.filter(kind=kind)
    if kind in BALANCE_KINDS:
        accounts = accounts.with_balance()
    account = get_object_or_404(accounts.select_related("pays_from"), pk=pk)
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
    page = paginate(request, transactions)
    history = months(account, today)
    privacy_mode = cast("User", request.user).privacy_mode
    return render(
        request,
        "accounts/account_transactions.html",
        {
            "account": account,
            "kind": Account.Kind(kind),
            "title": KIND_TITLES[Account.Kind(kind)],
            "page": page,
            "rows": rows(account, list(page)),
            "count": page.paginator.count,
            "this_month": history[-1],
            "last_month": history[-2],
            "average": sum((m.net for m in history[:-1]), Decimal(0))
            / (len(history) - 1),
            "year_total": sum(
                (m.net for m in history if m.start.year == today.year), Decimal(0)
            ),
            "bars": []
            if privacy_mode
            else bars(
                [m.start for m in history],
                [m.balance if account.has_opening_balance else m.net for m in history],
            ),
            "forecast": _account_forecast(account),
            "used_by": _used_by(account),
            "today": today,
            "here": request.get_full_path(),
            "statements": account.statements.select_related("transaction").order_by(
                "-period_end"
            )[:STATEMENTS_SHOWN],
            "card_emis": [
                (emi, emi.progress(today))
                for emi in account.card_emis.select_related("card", "purchase__party")
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


def _form_page(request: HttpRequest, kind: str, account: Account) -> HttpResponseBase:
    form = AccountForm(request.POST or None, instance=account)
    editing = account.pk is not None
    if form.is_valid() and save_unique_name(form, form.duplicate_name_error):
        messages.success(
            request, f"Saved {account}." if editing else f"Added {account}."
        )
        return redirect("account_transactions", kind=kind, pk=account.pk)
    return render(
        request,
        "accounts/account_form.html",
        {
            "form": form,
            "kind": Account.Kind(kind),
            "account": account if editing else None,
        },
    )


@login_required
def account_create(request: HttpRequest, kind: str) -> HttpResponseBase:
    """Create an Account of the kind in the URL."""
    return _form_page(request, kind, Account(kind=kind))


@login_required
@blocked_in_privacy_mode
def account_edit(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Edit an Account, which must be of the kind in the URL."""
    return _form_page(request, kind, get_object_or_404(Account, pk=pk, kind=kind))


def _set_hidden(
    request: HttpRequest, kind: str, pk: int, *, hidden: bool
) -> HttpResponseBase:
    account = get_object_or_404(Account, pk=pk, kind=kind)
    account.hidden = hidden
    account.save()
    messages.success(
        request,
        f"Hid {account}. It keeps its Transactions."
        if hidden
        else f"{account} is back in the list.",
    )
    return redirect("account_transactions", kind=kind, pk=pk)


@login_required
@require_POST
def account_hide(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Hide an Account from its kind's list and from new Transactions."""
    return _set_hidden(request, kind, pk, hidden=True)


@login_required
@require_POST
def account_unhide(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Show a hidden Account in its kind's list again."""
    return _set_hidden(request, kind, pk, hidden=False)


@login_required
def account_delete(request: HttpRequest, kind: str, pk: int) -> HttpResponseBase:
    """Confirm, then delete an Account of the kind in the URL."""
    account = get_object_or_404(Account, pk=pk, kind=kind)
    if used_by := _used_by(account):
        noun = f"{Account.Kind(kind).label} Account"
        merge_url = reverse("account_merge", kwargs={"kind": kind, "pk": pk})
        return redirect_in_use_to_merge(
            request, account, noun, merge_url, used_by=used_by
        )
    if request.method == "POST":
        account.delete()
        messages.success(request, f"Deleted {account}.")
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
            return redirect("account_transactions", kind=kind, pk=merge.target.pk)
    return render(
        request,
        "accounts/account_merge.html",
        {"form": form, "kind": Account.Kind(kind), "source": source, "merge": merge},
    )
