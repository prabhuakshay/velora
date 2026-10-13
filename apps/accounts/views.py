"""Views for managing Accounts, one set shared by every kind."""

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts import forecast_view
from apps.accounts.activity import bars, month_end, months, rows, touching_transactions
from apps.accounts.forecast import DAYS, forecast
from apps.accounts.forms import AccountForm, ReconcileForm
from apps.accounts.merge import AccountMerge
from apps.accounts.models import BALANCE_KINDS, Account
from apps.accounts.reconciliation_views import reconciliation_status
from apps.core.dates import months_after
from apps.core.forms import MergeForm
from apps.core.views import paginate, redirect_in_use_to_merge, save_unique_name
from apps.investments.valuation import account_value
from apps.investments.views import investment_tabs
from apps.transactions.models import Split
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

    from apps.users.models import User

SIDE_LIST_SHOWN = 5


@login_required
def forecast_page(request: HttpRequest) -> HttpResponse:
    """One Account's, or all Assets', expected Balance and what moves it."""
    length = _choice(request.GET.get("days"), forecast_view.HORIZONS, DAYS)
    result = forecast(timezone.localdate(), length)
    account_pk = request.GET.get("account", "")
    scope = forecast_view.scope_for(
        result, int(account_pk) if account_pk.isdigit() else None
    )
    days = forecast_view.timeline(scope, result)
    return render(
        request,
        "accounts/forecast.html",
        {
            "forecast": result,
            "length": length,
            "scope": scope,
            "days": days,
            "totals": forecast_view.totals(days),
            "worst": forecast_view.worst(scope, result),
            "chart": forecast_view.chart(scope, result, days),
            "rows": forecast_view.account_rows(result, scope.account, length),
            "horizons": forecast_view.horizon_tabs(length, scope.account),
            "all_url": f"{reverse('forecast')}?days={length}",
            "unknown": sum(
                entry.change is None for day in days for entry in day.entries
            ),
        },
    )


def _choice(raw: str | None, choices: tuple[int, ...], default: int) -> int:
    """The GET value when it is one of the choices, else the default."""
    return int(raw) if raw and raw.isdigit() and int(raw) in choices else default


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
        else "Investment Events"
        if account.investment_events.exists()
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
            "owes": kind == Account.Kind.LIABILITY,
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
    worst = (max if account.owes else min)(
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
    page = paginate(request, touching_transactions(account))
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
                owes=account.owes,
            ),
            "forecast": _account_forecast(account),
            "investment": account_value(account, account.balance)
            if account.is_investment
            else None,
            "tabs": investment_tabs(account, "account_transactions")
            if account.is_investment
            else None,
            "reconcile_form": ReconcileForm(account=account)
            if account.has_opening_balance
            else None,
            **reconciliation_status(account, SIDE_LIST_SHOWN),
            "used_by": _used_by(account),
            "today": today,
            "here": request.get_full_path(),
            "statements": account.statements.listed()[:SIDE_LIST_SHOWN],
            "statement_count": account.statements.count(),
            "shown": SIDE_LIST_SHOWN,
            "card_emis": [
                (emi, emi.progress(today))
                for emi in account.card_emis.select_related("card", "purchase__party")
            ],
            # Purchases off the card that can still become a Card EMI.
            "emi_candidates": set(
                Split.objects.filter(
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
