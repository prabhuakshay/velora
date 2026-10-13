"""Views for credit card Statements and Card EMIs."""

from copy import copy
from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.cards.forms import CardEMIForm, ForecloseForm, StatementForm
from apps.cards.models import CardEMI, Statement
from apps.cards.plans import Plan
from apps.cards.statements import (
    enter_actual_amount,
    estimate,
    payment_candidates,
    refresh_estimates,
    settle,
    unsettle,
)
from apps.quick_add.models import Draft
from apps.transactions.models import Transaction
from apps.users.privacy_mode import blocked_in_privacy_mode

PLAN_TERMS = ("principal", "months", "annual_rate", "processing_fee", "first_statement")

if TYPE_CHECKING:
    from django.http import HttpRequest, QueryDict
    from django.http.response import HttpResponseBase


def _bound_data(request: HttpRequest) -> QueryDict | None:
    """POST to save; a GET with terms only previews what they would do."""
    if request.method == "POST":
        return request.POST
    return request.GET or None


@login_required
@blocked_in_privacy_mode
def statement_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Enter the actual Statement Amount, which then replaces the estimate."""
    statement = get_object_or_404(Statement.objects.select_related("card"), pk=pk)
    card = statement.card
    form = StatementForm(request.POST or None, instance=statement)
    if form.is_valid():
        enter_actual_amount(statement, form.cleaned_data["actual_amount"])
        messages.success(
            request, f"Saved the Statement due {statement.due_date:%-d %b %Y}."
        )
        return redirect("account_transactions", kind=card.kind, pk=card.pk)
    statements = card.statements.order_by("period_end")
    today = timezone.localdate()
    candidates = []
    if not statement.is_paid:
        candidates = sorted(
            payment_candidates(statement, today).order_by("date", "pk"),
            key=lambda payment: abs(payment.date - statement.due_date),
        )
    return render(
        request,
        "cards/statement_form.html",
        {
            "form": form,
            "statement": statement,
            "card": card,
            "today": today,
            "candidates": candidates,
            # Every one, so even one edited off the card can be unlinked.
            "payments": statement.payments.annotate(
                paid=Sum("splits__amount", filter=Q(splits__to_account=card))
            ).order_by("date", "pk"),
            "parts": estimate(card, statement.period_start, statement.period_end),
            "draft": Draft.objects.waiting().filter(statement=statement).first(),
            "older": statements.filter(period_end__lt=statement.period_end).last(),
            "newer": statements.filter(period_end__gt=statement.period_end).first(),
        },
    )


@login_required
@blocked_in_privacy_mode
@require_POST
def statement_link_payment(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Link a recorded payment the user picked, which may pay only a part."""
    statement = get_object_or_404(Statement.objects.select_related("card"), pk=pk)
    candidates = payment_candidates(statement, timezone.localdate())
    chosen = request.POST.get("transaction", "")
    payment = candidates.filter(pk=chosen).first() if chosen.isdigit() else None
    if statement.is_paid:
        messages.error(request, "This Statement is already paid.")
    elif payment is None:
        messages.error(
            request,
            "Pick a payment into the card, dated after the period closed and "
            "not linked to anything else.",
        )
    else:
        settle(statement, payment)
        messages.success(request, f"Linked the payment on {payment.date:%-d %b %Y}.")
    return redirect("statement_edit", pk=statement.pk)


@login_required
@blocked_in_privacy_mode
@require_POST
def statement_unlink_payment(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Unlink one of the Statement's payments when it was the wrong one."""
    statement = get_object_or_404(Statement.objects.select_related("card"), pk=pk)
    chosen = request.POST.get("transaction", "")
    payment = statement.payments.filter(pk=chosen).first() if chosen.isdigit() else None
    if payment:
        unsettle(statement, payment)
        messages.success(request, f"Unlinked the payment on {payment.date:%-d %b %Y}.")
    return redirect("statement_edit", pk=statement.pk)


def _planned(form: CardEMIForm) -> Plan | None:
    """The plan the terms entered so far describe, or None while any is missing."""
    if not form.is_bound:
        return None
    form.is_valid()
    terms = {name: form.cleaned_data.get(name) for name in PLAN_TERMS}
    terms["processing_fee"] = terms["processing_fee"] or Decimal(0)
    if None in terms.values():
        return None
    return Plan.of(
        CardEMI(purchase=form.instance.purchase, card=form.instance.card, **terms)
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
        _bound_data(request),
        instance=CardEMI(purchase=purchase, card=card),
        initial={"principal": spent},
    )
    if request.method == "POST" and form.is_valid():
        emi = form.save()
        refresh_estimates(card)
        messages.success(request, f"Made a Card EMI over {emi.months} months.")
        return redirect("card_emi_detail", pk=emi.pk)
    return render(
        request,
        "cards/card_emi_form.html",
        {
            "form": form,
            "purchase": purchase,
            "card": card,
            "spent": spent,
            "plan": _planned(form),
        },
    )


@login_required
def card_emi_detail(request: HttpRequest, pk: int) -> HttpResponseBase:
    """A Card EMI's installments: what's billed, what's next and what's left."""
    emi = get_object_or_404(
        CardEMI.objects.select_related("card", "purchase", "interest_account"),
        pk=pk,
    )
    today = timezone.localdate()
    plan = Plan.of(emi, today)
    return render(
        request,
        "cards/card_emi_detail.html",
        {
            "emi": emi,
            "plan": plan,
            "today": today,
            "finished": plan.next is None,
            "drafts": emi.drafts.filter(status=Draft.Status.WAITING).count(),
        },
    )


@login_required
@blocked_in_privacy_mode
def card_emi_foreclose(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Record paying off the rest, billed with the next Statement."""
    emi = get_object_or_404(
        CardEMI.objects.select_related("card", "purchase", "interest_account"),
        pk=pk,
    )
    # A copy, as a preview sets the foreclosure on the instance the form holds.
    before = Plan.of(copy(emi), timezone.localdate())
    form = ForecloseForm(
        _bound_data(request),
        instance=emi,
        initial={"foreclosed_on": timezone.localdate()},
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        refresh_estimates(emi.card)
        messages.success(request, "Foreclosed the Card EMI.")
        return redirect("card_emi_detail", pk=emi.pk)
    after = (
        Plan.of(emi, timezone.localdate())
        if form.is_bound and form.is_valid()
        else None
    )
    return render(
        request,
        "cards/card_emi_foreclose.html",
        {"form": form, "emi": emi, "plan": before, "after": after},
    )
