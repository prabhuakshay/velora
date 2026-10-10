"""Views for credit card Statements."""

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.cards.forms import StatementForm
from apps.cards.models import Statement
from apps.cards.statements import enter_actual_amount
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
