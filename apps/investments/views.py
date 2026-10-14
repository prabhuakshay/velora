"""Instrument pages, Investment Account Holdings and their Investment Events."""

from typing import TYPE_CHECKING, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Account
from apps.home.charts import line
from apps.investments.fetches import recent, statuses
from apps.investments.forms import InvestmentEventForm, ManualPriceForm
from apps.investments.history import last_each_month, value_chart, value_history
from apps.investments.models import Instrument, InvestmentEvent
from apps.investments.overselling import oversell_refusal
from apps.investments.portfolio import COLUMNS, Column, portfolio, sorting
from apps.investments.tasks import queue_backfill, queue_refresh
from apps.investments.valuation import account_value
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from apps.users.models import User


def _page(
    request: HttpRequest, instrument: Instrument, form: ManualPriceForm | None
) -> HttpResponseBase:
    latest = instrument.latest_price()
    history: list[tuple[date, Decimal]] = []
    if not cast("User", request.user).privacy_mode:
        history = list(instrument.prices.order_by("date").values_list("date", "price"))
    return render(
        request,
        "investments/instrument_detail.html",
        {
            "instrument": instrument,
            "latest": latest,
            "stale": latest is not None and latest.is_stale(timezone.localdate()),
            "form": form,
            "chart": line([p for _, p in history]) if len(history) > 1 else None,
            "month_ends": last_each_month(history),
            "chart_prices": [[day.isoformat(), f"{p:.4f}"] for day, p in history],
        },
    )


@login_required
def instrument_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
    """The Instrument, its latest Price and, if priced by hand, a Price form."""
    instrument = get_object_or_404(Instrument, pk=pk)
    form = ManualPriceForm(instrument=instrument) if instrument.manual_price else None
    return _page(request, instrument, form)


@login_required
@blocked_in_privacy_mode
def instrument_add_price(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Record a Price entered by hand; only for an Instrument with a manual Price."""
    instrument = get_object_or_404(Instrument, pk=pk, manual_price=True)
    form = ManualPriceForm(request.POST, instrument=instrument)
    if not form.is_valid():
        return _page(request, instrument, form)
    price = form.save()
    messages.success(request, f"Saved the Price for {price.date:%-d %b %Y}.")
    return redirect("instrument_detail", pk=pk)


def investment_account(pk: int) -> Account:
    """The Investment Account with its Balance, or 404."""
    return get_object_or_404(Account.objects.investment().with_balance(), pk=pk)


def investment_tabs(account: Account, current: str) -> list[dict[str, object]]:
    """Switch between an Investment Account's Transactions and Holdings."""
    return [
        {
            "title": title,
            "url": reverse(name, kwargs=kwargs),
            "active": name == current,
        }
        for title, name, kwargs in (
            (
                "Transactions",
                "account_transactions",
                {"kind": account.kind, "pk": account.pk},
            ),
            ("Holdings", "account_holdings", {"pk": account.pk}),
        )
    ]


@login_required
def account_holdings(request: HttpRequest, pk: int) -> HttpResponseBase:
    """An Investment Account's Holdings, Cash and Investment Events."""
    account = investment_account(pk)
    return render(
        request,
        "investments/account_holdings.html",
        {
            "account": account,
            "value": account_value(account, account.balance),
            "events": account.investment_events.select_related(
                "instrument", "new_instrument"
            ),
            "tabs": investment_tabs(account, "account_holdings"),
            "today": timezone.localdate(),
        },
    )


def _event_form(
    request: HttpRequest, account: Account, event: InvestmentEvent
) -> HttpResponseBase:
    form = InvestmentEventForm(request.POST or None, instance=event, account=account)
    if form.is_valid():
        saved = form.save()
        if saved.kind == InvestmentEvent.Kind.BUY:
            queue_backfill()
        messages.success(request, f"Saved the {saved.get_kind_display()}.")
        return redirect("account_holdings", pk=account.pk)
    return render(
        request,
        "investments/event_form.html",
        {"form": form, "account": account, "event": event if event.pk else None},
    )


@login_required
def investment_event_create(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Record a Buy or Sell inside an Investment Account."""
    return _event_form(request, investment_account(pk), InvestmentEvent())


@login_required
@blocked_in_privacy_mode
def investment_event_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit an Investment Event; Lots, Cash and gains follow from the replay."""
    event = get_object_or_404(InvestmentEvent.objects.select_related("account"), pk=pk)
    return _event_form(request, event.account, event)


@login_required
@require_POST
def investment_event_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Delete an Investment Event and its Transaction, unless a Sell needs its units."""
    event = get_object_or_404(
        InvestmentEvent.objects.select_related("transaction"), pk=pk
    )
    if refusal := oversell_refusal(event.account, leaving_out=pk):
        messages.error(request, f"Can't delete it: {refusal}")
    else:
        event.delete()
        if event.transaction is not None:
            event.transaction.delete()
        messages.success(request, f"Deleted the {event.get_kind_display()}.")
    return redirect("account_holdings", pk=event.account_id)


def _headers(current: Column, *, descending: bool) -> list[dict[str, object]]:
    """Each Holdings column heading; the sorted one links to its other way."""
    return [
        {
            "title": column.title,
            "numeric": column.numeric,
            "url": f"?sort={'-' if column == current and not descending else ''}"
            f"{column.key}",
            "aria_sort": ("descending" if descending else "ascending")
            if column == current
            else "",
        }
        for column in COLUMNS
    ]


@login_required
def investments_overview(request: HttpRequest) -> HttpResponseBase:
    """The portfolio's totals, each Investment Account and every Holding."""
    held = portfolio()
    column, descending = sorting(request.GET.get("sort", ""))
    history = []
    if not cast("User", request.user).privacy_mode:
        history = value_history(timezone.localdate())
    return render(
        request,
        "investments/overview.html",
        {
            "accounts": held.accounts,
            "totals": held.totals,
            "kinds": held.by_kind(),
            "columns": _headers(column, descending=descending),
            "holdings": held.holdings(column, descending=descending),
            "history": history,
            "chart": value_chart(history),
            "price_statuses": statuses(),
        },
    )


@login_required
def price_fetches(request: HttpRequest) -> HttpResponseBase:
    """Every Price Fetch of the last 90 days, newest first."""
    return render(
        request,
        "investments/price_fetches.html",
        {"fetches": recent(timezone.localdate())},
    )


@login_required
@require_POST
def investments_refresh_prices(request: HttpRequest) -> HttpResponseBase:
    """Queue a fetch of today's Prices and the missing past ones."""
    queue_refresh()
    messages.success(request, "Refreshing Prices. They will update shortly.")
    return redirect("investments_overview")
