"""Forms for credit card Statements."""

from typing import ClassVar

from django import forms

from apps.cards.models import Statement


class StatementForm(forms.ModelForm[Statement]):
    """Enter the actual Statement Amount from the real statement."""

    class Meta:
        model = Statement
        fields = ("actual_amount",)
        labels: ClassVar = {"actual_amount": "Actual Statement Amount"}
