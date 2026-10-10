"""The Quick Add box and the hand-made Draft form."""

from typing import Any, ClassVar, cast

from django import forms
from django.db.models.functions import Lower
from django.utils import timezone

from apps.classification.models import Party, Tag
from apps.quick_add.models import Draft, DraftSplit, QuickAdd
from apps.transactions.forms import (
    MultipleFileField,
    offer_accounts,
    offer_parties,
)


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


class DraftEditForm(forms.ModelForm[Draft]):
    """A Draft as the user edits it, saved with any gaps still open.

    Attachments are only carried to the Transaction when the Draft is posted.
    """

    attachments = MultipleFileField(
        required=False, help_text="Added when the Draft is posted."
    )

    class Meta:
        model = Draft
        fields = ("date", "party", "new_party_name", "description")
        labels: ClassVar = {"new_party_name": "New Party"}
        help_texts: ClassVar = {
            "new_party_name": "Created on post when no Party is picked above."
        }
        widgets: ClassVar = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        offer_parties(self)

    def clean(self) -> dict[str, Any]:
        """A picked Party wins over a new Party name."""
        super().clean()
        cleaned = self.cleaned_data
        if cleaned.get("party"):
            cleaned["new_party_name"] = ""
        return cleaned


class DraftSplitForm(forms.ModelForm[DraftSplit]):
    """One Split of a Draft; any part of it may still be blank.

    Tags are only carried to the Transaction when the Draft is posted.
    """

    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = DraftSplit
        fields = ("from_account", "to_account", "amount")
        labels: ClassVar = {"from_account": "From", "to_account": "To"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        offer_accounts(self)
        for name in ("from_account", "to_account"):
            self.fields[name].required = False
        tags = cast("forms.ModelMultipleChoiceField[Tag]", self.fields["tags"])
        tags.queryset = Tag.objects.filter(hidden=False).order_by(Lower("name"))


DraftSplitFormSet = forms.inlineformset_factory(
    Draft, DraftSplit, form=DraftSplitForm, extra=0, can_delete=True
)
