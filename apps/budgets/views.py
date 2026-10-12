"""The Budgets page: a table of every Budget, each cell saved as it changes."""

from datetime import date
from functools import wraps
from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Account, AccountKind
from apps.budgets.forms import BudgetAmountForm
from apps.budgets.models import set_budget
from apps.budgets.picture import BudgetRow, UnbudgetedRow, budget_picture
from apps.core.dates import month_start, months_after
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from apps.users.models import User

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

    Cells send the month they were opened in, so a page left open as the month
    turned can't change the new month by mistake.
    """

    @wraps(view)
    def wrapper(
        request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        sent = request.POST.get("month") or request.GET.get("month")
        if sent is not None and sent != f"{_this_month():%Y-%m}":
            messages.error(request, "Budgets can be changed only for this month.")
            if request.headers.get("HX-Request"):
                # htmx would follow a redirect unseen, so ask it to load the page.
                return HttpResponse(headers={"HX-Redirect": reverse("budget_list")})
            return redirect("budget_list")
        return view(request, *args, **kwargs)

    return wrapper


@login_required
def budget_list(request: HttpRequest) -> HttpResponseBase:
    """A month's Budgets against what was Spent, this month by default."""
    month = _month(request)
    current = month == _this_month()
    picture = budget_picture(month, expected=True)
    return render(
        request,
        "budgets/budget_list.html",
        {
            "picture": picture,
            "sheet": picture.sheet if current else picture.rows,
            "previous": months_after(month, -1),
            "next": None if current else months_after(month, 1),
            "current": current,
            "editable": current and not cast("User", request.user).privacy_mode,
        },
    )


@login_required
@this_month_only
@blocked_in_privacy_mode
@require_POST
def budget_edit(request: HttpRequest, pk: int | None = None) -> HttpResponseBase:
    """Save one cell of the Budgets table and send back what it changed.

    With no Account it is the Overall Budget's cell.
    """
    account = (
        None
        if pk is None
        else get_object_or_404(Account, pk=pk, kind=AccountKind.EXPENSE)
    )
    form = BudgetAmountForm(request.POST)
    if form.is_valid():
        set_budget(account, form.cleaned_data["amount"], timezone.localdate())
    picture = budget_picture(_this_month(), expected=True)
    rows: list[BudgetRow | UnbudgetedRow] = [*picture.rows, *picture.unbudgeted_rows]
    row = next((row for row in rows if row.account == account), None)
    return render(
        request,
        "budgets/_saved.html",
        {
            "picture": picture,
            "row": row,
            "fid": "overall" if account is None else f"budget-{account.pk}",
            "errors": form["amount"].errors,
        },
    )
