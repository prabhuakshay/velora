"""The Budgets page and setting, changing and removing a Budget."""

from datetime import date
from functools import wraps
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Account, AccountKind
from apps.budgets.forms import BudgetForm, OverallBudgetForm
from apps.budgets.models import set_budget
from apps.budgets.picture import budget_picture, budgets_in, overall_budget_in
from apps.core.dates import month_start, months_after
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    type View = Callable[..., HttpResponseBase]


def _this_month() -> date:
    return month_start(timezone.localdate())


def _month(request: HttpRequest) -> date:
    """The first day of the month asked for, this month when none is given."""
    this_month = _this_month()
    asked = request.GET.get("month")
    if asked is None:
        return this_month
    try:
        month = date.fromisoformat(f"{asked}-01")
    except ValueError:
        raise Http404 from None
    if month > this_month:
        raise Http404
    return month


def this_month_only(view: View) -> View:
    """Refuse an edit sent for any month but this one; past months are read-only.

    Forms send the month they were opened in, so one opened before the month
    turned can't change the new month by mistake.
    """

    @wraps(view)
    def wrapper(
        request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        sent = request.POST.get("month") or request.GET.get("month")
        if sent is not None and sent != f"{_this_month():%Y-%m}":
            messages.error(request, "Budgets can be changed only for this month.")
            return redirect("budget_list")
        return view(request, *args, **kwargs)

    return wrapper


@login_required
def budget_list(request: HttpRequest) -> HttpResponseBase:
    """A month's Budgets against what was Spent, this month by default."""
    month = _month(request)
    current = month == _this_month()
    return render(
        request,
        "budgets/budget_list.html",
        {
            "picture": budget_picture(month, expected=True),
            "previous": months_after(month, -1),
            "next": None if current else months_after(month, 1),
            "current": current,
        },
    )


@login_required
@this_month_only
@blocked_in_privacy_mode
def budget_set(request: HttpRequest) -> HttpResponseBase:
    """Set or change a Budget from the start of this month."""
    today = timezone.localdate()
    budgets = budgets_in(month_start(today))
    chosen = request.GET.get("account", "")
    current = budgets.get(int(chosen)) if chosen.isdigit() else None
    form = BudgetForm(
        budgets,
        request.POST or None,
        initial={"account": chosen, "amount": current},
    )
    if form.is_valid():
        account = form.cleaned_data["account"]
        set_budget(account, form.cleaned_data["amount"], today)
        messages.success(request, f"Saved the Budget for {account}.")
        return redirect("budget_list")
    return render(
        request,
        "budgets/budget_form.html",
        {"form": form, "has_budget": current is not None, "account_pk": chosen},
    )


@login_required
@this_month_only
@require_POST
def budget_remove(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Remove a Budget from the start of this month; earlier months keep it."""
    account = get_object_or_404(Account, pk=pk, kind=AccountKind.EXPENSE)
    set_budget(account, None, timezone.localdate())
    messages.success(request, f"Removed the Budget for {account} from this month on.")
    return redirect("budget_list")


@login_required
@this_month_only
@blocked_in_privacy_mode
def overall_budget_set(request: HttpRequest) -> HttpResponseBase:
    """Set or change the Overall Budget from the start of this month."""
    today = timezone.localdate()
    current = overall_budget_in(month_start(today))
    form = OverallBudgetForm(request.POST or None, initial={"amount": current})
    if form.is_valid():
        set_budget(None, form.cleaned_data["amount"], today)
        messages.success(request, "Saved the Overall Budget.")
        return redirect("budget_list")
    return render(
        request,
        "budgets/overall_budget_form.html",
        {"form": form, "has_budget": current is not None},
    )


@login_required
@this_month_only
@require_POST
def overall_budget_remove(request: HttpRequest) -> HttpResponseBase:
    """Remove the Overall Budget from the start of this month."""
    set_budget(None, None, timezone.localdate())
    messages.success(request, "Removed the Overall Budget from this month on.")
    return redirect("budget_list")
