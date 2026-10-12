"""The home dashboard."""

from typing import TYPE_CHECKING, cast

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.accounts import forecast_view
from apps.accounts.forecast import DAYS, forecast
from apps.budgets.picture import budget_picture
from apps.core.dates import month_start, months_after
from apps.home import dashboard
from apps.schedules.subscriptions import subscription_costs, yearly_total

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

    from apps.users.models import User


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Net Worth, this month's money, where it went and what is coming up."""
    today = timezone.localdate()
    privacy_mode = cast("User", request.user).privacy_mode
    chosen = request.GET.get("range", "")
    range_key = chosen if chosen in dashboard.RANGES else dashboard.DEFAULT_RANGE
    flows = dashboard.cash_flow(today)
    outlook = forecast(today, DAYS)
    scope = forecast_view.scope_for(outlook, None)
    costs = subscription_costs(today)
    budgets = budget_picture(month_start(today))
    return render(
        request,
        "index.html",
        {
            "today": today,
            "hour": timezone.localtime().hour,
            "ranges": dashboard.RANGES,
            "range": range_key,
            "net_worth": dashboard.net_worth_card(
                today, dashboard.RANGES[range_key], charted=not privacy_mode
            ),
            "this_month": flows[-1],
            "last_month": flows[-2],
            "spent_by_now_last_month": dashboard.spent_by_now_last_month(today),
            "same_day_last_month": months_after(today, -1),
            "flow_columns": dashboard.flow_columns(flows),
            "spending": dashboard.spending(today),
            "outlook": outlook,
            "scope": scope,
            "worst": forecast_view.worst(scope, outlook),
            "outlook_chart": forecast_view.chart(
                scope, outlook, forecast_view.timeline(scope, outlook)
            ),
            "cards": dashboard.cards(today),
            "budgets": dashboard.budget_card(budgets),
            "budget_picture": budgets,
            "subscriptions_monthly": yearly_total(costs) / 12,
            "subscriptions_count": sum(cost.counted for cost in costs),
            "recent": dashboard.recent_transactions(),
        },
    )
