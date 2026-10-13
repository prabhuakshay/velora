"""Forms for Accounts."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms
from django.db.models import Min, Q
from django.utils import timezone

from apps.accounts.models import (
    CARD_SETTINGS_TOGETHER,
    DIRECT_NEEDS_BANKS,
    Account,
    Reconciliation,
)
from apps.core.forms import clean_unique_name
from apps.transactions.models import Split

if TYPE_CHECKING:
    import datetime
    from datetime import date

OPENING_BALANCE_FIELDS = ("opening_balance", "opening_balance_date")
BALANCE_KIND_FIELDS = (
    *OPENING_BALANCE_FIELDS,
    "include_in_net_worth",
    "low_balance_threshold",
)
CARD_FIELDS = ("statement_day", "due_day", "pays_from")
DIRECT_FIELDS = ("invests_from", "invests_into")
CARD_IN_USE = (
    "This card has Statements or Card EMIs, so its card settings can't be cleared."
)
NEGATIVE_LIABILITY_THRESHOLD = "Enter 0 or more."


class AccountForm(forms.ModelForm[Account]):
    """Create or edit an Account; the kind comes from the instance, never the form.

    Only Asset and Liability Accounts get the Opening Balance, Net Worth and
    Low-Balance Threshold fields, only Liability Accounts the credit card
    settings, and only Asset Accounts the investment mode, fixed once created.
    """

    class Meta:
        model = Account
        fields = (
            "name",
            "notes",
            "investment_mode",
            *DIRECT_FIELDS,
            *BALANCE_KIND_FIELDS,
            *CARD_FIELDS,
        )
        widgets: ClassVar = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "opening_balance_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self._set_up_investment_mode()
        if not self.instance.owes:
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
        if self.instance.owes:
            threshold.label = "Warn when owing over"
            threshold.help_text = (
                "Warn when the Forecast expects you to owe more than this; "
                "0 for no warning."
            )
        self.fields["opening_balance"].label = "Opening Balance"
        self.fields["opening_balance_date"].label = "Opening Balance date"
        if not self.instance.pk:
            self.initial["opening_balance"] = Decimal(0)
            self.initial["opening_balance_date"] = timezone.localdate()

    def _set_up_investment_mode(self) -> None:
        account = self.instance
        is_asset = account.kind == Account.Kind.ASSET
        # Pays from and Pays into can change later, but only on a Direct one.
        for name in DIRECT_FIELDS:
            if not is_asset or (account.pk and not account.is_direct):
                del self.fields[name]
            else:
                self.fields[name].help_text = "Only for a Direct Investment Account."
        if not is_asset:
            del self.fields["investment_mode"]
            return
        mode = cast("forms.ChoiceField", self.fields["investment_mode"])
        mode.choices = [("", "No"), *Account.InvestmentMode.choices]
        mode.disabled = account.pk is not None
        mode.help_text = "For a broker or fund platform. This can't be changed later."

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
        if DIRECT_FIELDS[0] in self.fields:
            self._clean_direct_banks()
        return cleaned

    def _clean_direct_banks(self) -> None:
        cleaned = self.cleaned_data
        mode = cleaned.get("investment_mode", self.instance.investment_mode)
        if mode != Account.InvestmentMode.DIRECT:
            for name in DIRECT_FIELDS:
                cleaned[name] = None
        elif not all(cleaned.get(name) for name in DIRECT_FIELDS):
            raise forms.ValidationError(DIRECT_NEEDS_BANKS)

    def clean_low_balance_threshold(self) -> Decimal:
        """A blank threshold is the default, 0; a Liability's can't be negative."""
        threshold: Decimal | None = self.cleaned_data["low_balance_threshold"]
        if threshold is None:
            return Decimal(0)
        if threshold < 0 and self.instance.owes:
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
        return clean_unique_name(
            self,
            Account.objects.filter(kind=self.instance.kind),
            self.duplicate_name_error,
        )


class ReconcileForm(forms.Form):
    """The bank's balance for an Account on a day, refused unless it matches.

    A Liability's balance is entered as what is owed (ADR 0009). After a
    refusal, difference is the entered balance less Velora's Balance that day.
    """

    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    balance = forms.DecimalField(max_digits=15, decimal_places=2)

    def __init__(self, *args: Any, account: Account, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.account = account
        self.difference = Decimal(0)
        self.initial.setdefault("date", timezone.localdate())
        if account.owes:
            self.fields["balance"].label = "What you owed"
            self.fields[
                "balance"
            ].help_text = "Put a minus sign before a credit balance."

    def clean_date(self) -> datetime.date:
        """Refuse a day after today or before the Account's Opening Balance date."""
        when: datetime.date = self.cleaned_data["date"]
        if when > timezone.localdate():
            message = "Pick today or earlier."
            raise forms.ValidationError(message)
        if self.account.opens_after(when):
            opened = self.account.opening_balance_date
            message = f"This Account opens on {opened:%-d %b %Y}; pick that or later."
            raise forms.ValidationError(message)
        return when

    def clean(self) -> dict[str, Any]:
        """Refuse a balance that differs from Velora's by even a paisa."""
        super().clean()
        cleaned = self.cleaned_data
        when, balance = cleaned.get("date"), cleaned.get("balance")
        if when is None or balance is None:
            return cleaned
        self.difference = balance - self.account.balance_on(when)
        if self.difference:
            message = f"That doesn't match Velora's Balance on {when:%-d %b %Y}."
            raise forms.ValidationError(message)
        return cleaned

    def save(self) -> Reconciliation:
        """Record the Reconciliation, replacing any on the same day."""
        reconciliation, _ = Reconciliation.objects.update_or_create(
            account=self.account,
            date=self.cleaned_data["date"],
            defaults={
                "balance": self.cleaned_data["balance"],
                "created_at": timezone.now(),
            },
        )
        return reconciliation
