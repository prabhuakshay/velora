"""The Quick Add box."""

from django import forms

from apps.quick_add.models import QuickAdd


class QuickAddForm(forms.ModelForm[QuickAdd]):
    """One sentence about a money event."""

    class Meta:
        model = QuickAdd
        fields = ("text",)
        labels = {"text": "Quick Add"}
        error_messages = {
            "text": {
                "required": "Write what happened, like “lunch at Toit 850 on hdfc”.",
            }
        }
