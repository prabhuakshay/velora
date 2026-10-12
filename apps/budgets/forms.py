"""The form for setting or changing a Budget."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import Q
from django.db.models.functions import Lower

from apps.accounts.models import Account, AccountKind

if TYPE_CHECKING:
    from collections.abc import Iterable


def amount_field(help_text: str) -> forms.DecimalField:
    """A Budget amount: 0 or more, where 0 means spend nothing."""
    return forms.DecimalField(
        label="Budget",
        max_digits=15,
        decimal_places=2,
        min_value=Decimal(0),
        error_messages={"min_value": "Enter 0 or more."},
        help_text=help_text,
    )


class BudgetForm(forms.Form):
    """Choose an Expense Account and the most to spend under it each month.

    Hidden Expense Accounts are offered only while they have a Budget, so it
    can still be changed.
    """

    account: forms.ModelChoiceField[Account] = forms.ModelChoiceField(
        queryset=Account.objects.none(), label="Expense Account"
    )
    amount = amount_field(
        "The most to spend under it each month. 0 means spend nothing."
    )

    def __init__(self, budgeted: Iterable[int], *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(  # type: ignore[attr-defined]
            Q(hidden=False) | Q(pk__in=budgeted), kind=AccountKind.EXPENSE
        ).order_by(Lower("name"))


class OverallBudgetForm(forms.Form):
    """The most to spend across all Expense Accounts each month."""

    amount = amount_field(
        "The most to spend in a month, Unbudgeted spending included. "
        "0 means spend nothing."
    )
