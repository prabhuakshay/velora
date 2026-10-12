"""The Budgets page and setting, changing and removing a Budget."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Account, AccountKind
from apps.budgets.forms import BudgetForm
from apps.budgets.models import set_budget
from apps.budgets.picture import budget_picture, budgets_in
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase


@login_required
def budget_list(request: HttpRequest) -> HttpResponseBase:
    """This month's Budgets against what was Spent."""
    month = timezone.localdate().replace(day=1)
    return render(
        request, "budgets/budget_list.html", {"picture": budget_picture(month)}
    )


@login_required
@blocked_in_privacy_mode
def budget_set(request: HttpRequest) -> HttpResponseBase:
    """Set or change a Budget from the start of this month."""
    today = timezone.localdate()
    budgets = budgets_in(today.replace(day=1))
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
        {"form": form, "removable": int(chosen) if current is not None else None},
    )


@login_required
@require_POST
def budget_remove(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Remove a Budget from the start of this month; earlier months keep it."""
    account = get_object_or_404(Account, pk=pk, kind=AccountKind.EXPENSE)
    set_budget(account, None, timezone.localdate())
    messages.success(request, f"Removed the Budget for {account} from this month on.")
    return redirect("budget_list")
