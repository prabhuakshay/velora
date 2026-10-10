"""Forms for Accounts."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.db.models import Min, Q
from django.utils import timezone

from apps.accounts.models import CARD_SETTINGS_TOGETHER, Account
from apps.transactions.models import Split

if TYPE_CHECKING:
    from datetime import date

OPENING_BALANCE_FIELDS = ("opening_balance", "opening_balance_date")
BALANCE_KIND_FIELDS = (
    *OPENING_BALANCE_FIELDS,
    "include_in_net_worth",
    "low_balance_threshold",
)
CARD_FIELDS = ("statement_day", "due_day", "pays_from")
CARD_IN_USE = (
    "This card has Statements or Card EMIs, so its card settings can't be cleared."
)
NEGATIVE_LIABILITY_THRESHOLD = "Enter 0 or more."


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
        threshold = self.fields["low_balance_threshold"]
        threshold.required = False
        if self.instance.kind == Account.Kind.LIABILITY:
            threshold.label = "Warn when owing over"
            threshold.help_text = (
                "Warn when the Forecast expects you to owe more than this; "
                "0 for no warning."
            )
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
        """Refuse card settings unless all three are given.

        Nor may they be cleared while the card has Statements or Card EMIs.
        """
        super().clean()
        cleaned = self.cleaned_data
        if CARD_FIELDS[0] in self.fields:
            given = [cleaned.get(name) is not None for name in CARD_FIELDS]
            if any(given) and not all(given):
                raise forms.ValidationError(CARD_SETTINGS_TOGETHER)
            card = self.instance
            if (
                not any(given)
                and card.pk
                and (card.statements.exists() or card.card_emis.exists())
            ):
                raise forms.ValidationError(CARD_IN_USE)
        return cleaned

    def clean_low_balance_threshold(self) -> Decimal:
        """A blank threshold is the default, 0; a Liability's can't be negative."""
        threshold: Decimal | None = self.cleaned_data["low_balance_threshold"]
        if threshold is None:
            return Decimal(0)
        if threshold < 0 and self.instance.kind == Account.Kind.LIABILITY:
            raise forms.ValidationError(NEGATIVE_LIABILITY_THRESHOLD)
        return threshold

    def clean_opening_balance_date(self) -> date:
        """Refuse a date after the Account's earliest Split, which would drop it."""
        opening: date = self.cleaned_data["opening_balance_date"]
        if not self.instance.pk:
            return opening
        earliest = Split.objects.filter(
            Q(from_account=self.instance) | Q(to_account=self.instance)
        ).aggregate(earliest=Min("transaction__date"))["earliest"]
        if earliest is not None and opening > earliest:
            message = (
                f"This Account has Transactions from {earliest:%-d %b %Y}; "
                "pick that date or earlier."
            )
            raise forms.ValidationError(message)
        return opening

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
