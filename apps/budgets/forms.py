"""The form behind each cell of the Budgets table."""

from decimal import Decimal

from django import forms


class BudgetAmountForm(forms.Form):
    """A Budget amount: empty removes the Budget, 0 means spend nothing."""

    amount = forms.DecimalField(
        required=False,
        max_digits=15,
        decimal_places=2,
        min_value=Decimal(0),
        error_messages={"min_value": "Enter 0 or more."},
    )
