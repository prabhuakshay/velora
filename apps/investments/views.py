"""The Instrument page, with its latest Price and hand-entered Prices."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.investments.forms import ManualPriceForm
from apps.investments.models import Instrument
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase


def _page(
    request: HttpRequest, instrument: Instrument, form: ManualPriceForm | None
) -> HttpResponseBase:
    latest = instrument.latest_price()
    return render(
        request,
        "investments/instrument_detail.html",
        {
            "instrument": instrument,
            "latest": latest,
            "stale": latest is not None and latest.is_stale(timezone.localdate()),
            "form": form,
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
