"""Forms for credit card Statements and Card EMIs."""

from copy import copy
from datetime import date, timedelta
from itertools import islice
from typing import Any, ClassVar

from django import forms
from django.core.validators import MaxValueValidator

from apps.cards.models import CardEMI, Statement
from apps.cards.statements import closing_dates

# How many Statements after the purchase the first installment can be billed in.
FIRST_STATEMENT_CHOICES = 3
# Longer than any card's EMI plans, and keeps the schedule a readable length.
MAX_MONTHS = 120


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
        months: forms.IntegerField = self.fields["months"]  # type: ignore[assignment]
        months.max_value = MAX_MONTHS
        months.validators.append(MaxValueValidator(MAX_MONTHS))
        months.widget.attrs.update(min=1, max=MAX_MONTHS, list="emi-months")


class ForecloseForm(forms.ModelForm[CardEMI]):
    """Pay off the rest of a Card EMI with the next Statement."""

    foreclosed_on = forms.DateField(
        label="Foreclosed on", widget=forms.DateInput(attrs={"type": "date"})
    )
    foreclosure_fee = forms.DecimalField(min_value=0, max_digits=15, decimal_places=2)

    class Meta:
        model = CardEMI
        fields = ("foreclosed_on", "foreclosure_fee")

    def clean_foreclosed_on(self) -> date:
        """Refuse a day before the purchase, or one after the last installment."""
        on: date = self.cleaned_data["foreclosed_on"]
        probe = copy(self.instance)
        probe.foreclosed_on = on
        error = None
        if on < self.instance.purchase.date:
            error = "That's before the purchase was made."
        elif (probe.foreclosure_index or 0) >= probe.months:
            error = (
                "Every installment is billed by then, so nothing is left to foreclose."
            )
        if error:
            raise forms.ValidationError(error)
        return on
