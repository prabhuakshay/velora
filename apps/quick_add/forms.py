"""The Quick Add box and the hand-made Draft form."""

from typing import Any, ClassVar, cast

from django import forms
from django.db.models.functions import Lower
from django.utils import timezone

from apps.classification.models import Party
from apps.quick_add.models import PARTY_NAME_MAX_LENGTH, Draft, QuickAdd


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


class NewPartyForm(forms.Form):
    """The new Party a Draft names, created when it is posted."""

    new_party_name = forms.CharField(
        label="New Party",
        max_length=PARTY_NAME_MAX_LENGTH,
        required=False,
        help_text="Created on save when no Party is picked above.",
    )


class DraftForm(forms.ModelForm[Draft]):
    """A Draft the user starts by hand; only its date is needed."""

    class Meta:
        model = Draft
        fields = ("date", "party", "description")
        widgets: ClassVar = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.initial["date"] = timezone.localdate()
        party = cast("forms.ModelChoiceField[Party]", self.fields["party"])
        party.queryset = Party.objects.filter(hidden=False).order_by(Lower("name"))
