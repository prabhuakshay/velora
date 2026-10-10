"""Forms for credit card Statements and Card EMIs."""

from datetime import date, timedelta
from itertools import islice
from typing import Any, ClassVar

from django import forms

from apps.cards.models import CardEMI, Statement
from apps.cards.statements import closing_dates

# How many Statements after the purchase the first installment can be billed in.
FIRST_STATEMENT_CHOICES = 3


class StatementForm(forms.ModelForm[Statement]):
    """Enter the actual Statement Amount from the real statement."""

    class Meta:
        model = Statement
        fields = ("actual_amount",)
        labels: ClassVar = {"actual_amount": "Actual Statement Amount"}


class CardEMIForm(forms.ModelForm[CardEMI]):
    """Turn a card purchase into a Card EMI."""

    first_statement = forms.TypedChoiceField(
        label="First billed Statement", coerce=date.fromisoformat
    )

    class Meta:
        model = CardEMI
        fields = (
            "principal",
            "months",
            "annual_rate",
            "processing_fee",
            "first_statement",
            "interest_account",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        bought = self.instance.purchase.date
        closings = closing_dates(
            self.instance.card, bought - timedelta(days=1), bought + timedelta(days=95)
        )
        field: forms.TypedChoiceField = self.fields["first_statement"]  # type: ignore[assignment]
        field.choices = [
            (closing.isoformat(), f"Statement to {closing:%d %b %Y}")
            for closing in islice(closings, FIRST_STATEMENT_CHOICES)
        ]


class ForecloseForm(forms.ModelForm[CardEMI]):
    """Pay off the rest of a Card EMI with the next Statement."""

    foreclosed_on = forms.DateField(
        label="Foreclosed on", widget=forms.DateInput(attrs={"type": "date"})
    )
    foreclosure_fee = forms.DecimalField(min_value=0, max_digits=15, decimal_places=2)

    class Meta:
        model = CardEMI
        fields = ("foreclosed_on", "foreclosure_fee")
