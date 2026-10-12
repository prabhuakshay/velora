"""The form for setting or changing a Budget."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import Q
from django.db.models.functions import Lower

from apps.accounts.models import Account, AccountKind

if TYPE_CHECKING:
    from collections.abc import Iterable


class BudgetForm(forms.Form):
    """Choose an Expense Account and the most to spend under it each month.

    Hidden Expense Accounts are offered only while they have a Budget, so it
    can still be changed.
    """

    account: forms.ModelChoiceField[Account] = forms.ModelChoiceField(
        queryset=Account.objects.none(), label="Expense Account"
    )
    amount = forms.DecimalField(
        label="Budget",
        max_digits=15,
        decimal_places=2,
        min_value=Decimal(0),
        error_messages={"min_value": "Enter 0 or more."},
        help_text="The most to spend under it each month. 0 means spend nothing.",
    )

    def __init__(self, budgeted: Iterable[int], *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(  # type: ignore[attr-defined]
            Q(hidden=False) | Q(pk__in=budgeted), kind=AccountKind.EXPENSE
        ).order_by(Lower("name"))
