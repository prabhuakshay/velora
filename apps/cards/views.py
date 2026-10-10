"""Views for credit card Statements and Card EMIs."""

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import localdate

from apps.cards.forms import CardEMIForm, ForecloseForm, StatementForm
from apps.cards.models import CardEMI, Statement
from apps.cards.statements import enter_actual_amount, refresh_estimates
from apps.transactions.models import Transaction
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase


@login_required
@blocked_in_privacy_mode
def statement_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Enter the actual Statement Amount, which then replaces the estimate."""
    statement = get_object_or_404(Statement.objects.select_related("card"), pk=pk)
    form = StatementForm(request.POST or None, instance=statement)
    if form.is_valid():
        enter_actual_amount(statement, form.cleaned_data["actual_amount"])
        card = statement.card
        return redirect("account_transactions", kind=card.kind, pk=card.pk)
    return render(
        request, "cards/statement_form.html", {"form": form, "statement": statement}
    )


@login_required
@blocked_in_privacy_mode
def card_emi_create(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Turn a card purchase into a Card EMI, its principal the amount spent."""
    purchase = get_object_or_404(Transaction, pk=pk, card_emi__isnull=True)
    spends = purchase.splits.filter(from_account__statement_day__isnull=False)
    first = spends.select_related("from_account").first()
    if first is None:
        raise Http404
    card = first.from_account
    spent = spends.filter(from_account=card).aggregate(total=Sum("amount"))["total"]
    form = CardEMIForm(
        request.POST or None,
        instance=CardEMI(purchase=purchase, card=card),
        initial={"principal": spent},
    )
    if form.is_valid():
        form.save()
        refresh_estimates(card)
        return redirect("account_transactions", kind=card.kind, pk=card.pk)
    return render(
        request, "cards/card_emi_form.html", {"form": form, "purchase": purchase}
    )


@login_required
@blocked_in_privacy_mode
def card_emi_foreclose(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Record paying off the rest, billed with the next Statement."""
    emi = get_object_or_404(CardEMI.objects.select_related("card"), pk=pk)
    form = ForecloseForm(
        request.POST or None, instance=emi, initial={"foreclosed_on": localdate()}
    )
    if form.is_valid():
        form.save()
        refresh_estimates(emi.card)
        return redirect("account_transactions", kind=emi.card.kind, pk=emi.card.pk)
    return render(request, "cards/card_emi_foreclose.html", {"form": form, "emi": emi})
