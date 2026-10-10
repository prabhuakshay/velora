"""Forms for Accounts."""

from decimal import Decimal
from typing import Any, ClassVar

from django import forms
from django.utils import timezone

from apps.accounts.models import CARD_SETTINGS_TOGETHER, Account

OPENING_BALANCE_FIELDS = ("opening_balance", "opening_balance_date")
BALANCE_KIND_FIELDS = (
    *OPENING_BALANCE_FIELDS,
    "include_in_net_worth",
    "low_balance_threshold",
)
CARD_FIELDS = ("statement_day", "due_day", "pays_from")


class AccountForm(forms.ModelForm[Account]):
    """Create or edit an Account; the kind comes from the instance, never the form.

    Only Asset and Liability Accounts get the Opening Balance, Net Worth and
    Low-Balance Threshold fields, and only Liability Accounts the credit card settings.
    """

    class Meta:
        model = Account
        fields = ("name", "notes", *BALANCE_KIND_FIELDS, *CARD_FIELDS)
        widgets: ClassVar = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "opening_balance_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        if self.instance.kind != Account.Kind.LIABILITY:
            for name in CARD_FIELDS:
                del self.fields[name]
        if not self.instance.has_opening_balance:
            for name in BALANCE_KIND_FIELDS:
                del self.fields[name]
            return
        for name in OPENING_BALANCE_FIELDS:
            self.fields[name].required = True
        self.fields["low_balance_threshold"].required = False
        self.fields["opening_balance_date"].label = "Opening Balance date"
        if not self.instance.pk:
            self.initial["opening_balance"] = Decimal(0)
            self.initial["opening_balance_date"] = timezone.localdate()

    @property
    def duplicate_name_error(self) -> str:
        """The error shown when the name is taken within this kind."""
        label = Account.Kind(self.instance.kind).label
        return f"Another {label} Account already has this name."

    def clean(self) -> dict[str, Any]:
        """Refuse card settings unless all three are given."""
        super().clean()
        cleaned = self.cleaned_data
        if CARD_FIELDS[0] in self.fields:
            given = [cleaned.get(name) is not None for name in CARD_FIELDS]
            if any(given) and not all(given):
                raise forms.ValidationError(CARD_SETTINGS_TOGETHER)
        return cleaned

    def clean_low_balance_threshold(self) -> Decimal:
        """A blank threshold is the default, 0."""
        threshold: Decimal | None = self.cleaned_data["low_balance_threshold"]
        return Decimal(0) if threshold is None else threshold

    def clean_name(self) -> str:
        """Reject a name already in use within this kind, ignoring case."""
        name: str = self.cleaned_data["name"]
        kind = self.instance.kind
        clash = Account.objects.filter(kind=kind, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(self.duplicate_name_error)
        return name
