"""Forms for hand-entered Prices and Investment Events."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.investments.ledger import transaction_forms
from apps.investments.models import Instrument, InvestmentEvent, Price
from apps.investments.replay import OversoldError, replay

if TYPE_CHECKING:
    import datetime

    from apps.accounts.models import Account
    from apps.transactions.recording import TransactionForms

REPLAYED = ("kind", "date", "units", "amount", "charges")
UNKNOWN_ISIN = "Velora doesn't know this ISIN; enter the Instrument's name."


class ManualPriceForm(forms.Form):
    """A Price for a day; a second one for the same day replaces the first."""

    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    price = forms.DecimalField(
        max_digits=16, decimal_places=4, min_value=Decimal("0.0001")
    )

    def __init__(self, *args: Any, instrument: Instrument, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.instrument = instrument
        self.initial.setdefault("date", timezone.localdate())

    def clean_date(self) -> datetime.date:
        """Refuse a day after today."""
        when: datetime.date = self.cleaned_data["date"]
        if when > timezone.localdate():
            message = "Pick today or earlier."
            raise forms.ValidationError(message)
        return when

    def save(self) -> Price:
        """Store the Price for its day."""
        price, _ = Price.objects.update_or_create(
            instrument=self.instrument,
            date=self.cleaned_data["date"],
            defaults={"price": self.cleaned_data["price"]},
        )
        return price


def _future_refused(when: datetime.date) -> datetime.date:
    if when > timezone.localdate():
        message = "Pick today or earlier."
        raise forms.ValidationError(message)
    return when


def units_text(units: Decimal) -> str:
    """Units as plain digits, without trailing zeros."""
    return f"{units.normalize():f}"


def oversold_message(error: OversoldError) -> str:
    """Why a Sell can't take the units it asks for."""
    instrument = cast("InvestmentEvent", error.event).instrument
    return (
        f"Only {units_text(error.held)} units of {instrument} were held on "
        f"{error.event.date:%-d %b %Y}."
    )


class InvestmentEventForm(forms.ModelForm[InvestmentEvent]):
    """Record or edit a Buy or Sell inside an Investment Account.

    The Instrument is picked by ISIN; an ISIN Velora doesn't know becomes an
    Instrument with a manual Price, named by the form. A Sell taking more units
    than held on its date, counting every other event, is refused.
    """

    isin = forms.CharField(label="ISIN", max_length=12)
    instrument_name = forms.CharField(
        label="Instrument name",
        max_length=200,
        required=False,
        help_text="Only needed when Velora doesn't know the ISIN.",
    )
    instrument_kind = forms.ChoiceField(
        label="Instrument type",
        choices=Instrument.Kind.choices,
        initial=Instrument.Kind.STOCK,
        required=False,
    )

    class Meta:
        model = InvestmentEvent
        fields = ("kind", "date", "units", "price", "amount", "charges", "note")
        labels: ClassVar = {"kind": "Type"}
        help_texts: ClassVar = {
            "amount": "Units times Price, before charges.",
            "charges": "Brokerage, STT, stamp duty and other charges.",
        }
        widgets: ClassVar = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args: Any, account: Account, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.account = account
        self.instance.account = account
        for name in ("units", "price", "amount"):
            field = self.fields[name]
            field.required = True
            field.widget.attrs["min"] = "0"
        if self.instance.pk:
            self.initial["isin"] = self.instance.instrument.isin
        else:
            self.initial.setdefault("date", timezone.localdate())
        self.new_instrument: Instrument | None = None
        self.ledger: TransactionForms | None = None

    def clean_date(self) -> datetime.date:
        """Refuse a day after today."""
        return _future_refused(self.cleaned_data["date"])

    def clean_isin(self) -> str:
        """ISINs are kept in capitals."""
        return str(self.cleaned_data["isin"]).strip().upper()

    def clean(self) -> dict[str, Any]:
        """Find or make the Instrument, then refuse a Sell of units not held."""
        super().clean()
        cleaned = self.cleaned_data
        isin = cleaned.get("isin")
        if isin is None:
            return cleaned
        instrument = Instrument.objects.filter(isin=isin).first()
        if instrument is None:
            name = cleaned.get("instrument_name", "").strip()
            if not name:
                self.add_error("instrument_name", UNKNOWN_ISIN)
                return cleaned
            instrument = Instrument(
                isin=isin,
                name=name,
                kind=cleaned.get("instrument_kind") or Instrument.Kind.STOCK,
                manual_price=True,
            )
            self.new_instrument = instrument
        self.instance.instrument = instrument
        if not self.errors:
            # The instance only takes the form's values after clean(), so check a copy.
            candidate = InvestmentEvent(
                account=self.account,
                instrument=instrument,
                transaction=self.instance.transaction,
                **{name: cleaned[name] for name in REPLAYED},
            )
            self._refuse_overselling(candidate)
            self._check_ledger(candidate)
        return cleaned

    def _refuse_overselling(self, candidate: InvestmentEvent) -> None:
        others = self.account.investment_events.exclude(
            pk=self.instance.pk
        ).select_related("instrument")
        try:
            replay([*others, candidate])
        except OversoldError as error:
            raise forms.ValidationError(oversold_message(error)) from error

    def _check_ledger(self, candidate: InvestmentEvent) -> None:
        self.ledger = transaction_forms(candidate)
        if self.ledger is not None and not self.ledger.is_valid():
            for error in self.ledger.errors():
                self.add_error(None, f"Its Transaction can't be posted: {error}")

    @db_transaction.atomic
    def save(self, commit: bool = True) -> InvestmentEvent:  # noqa: FBT001, FBT002
        """Save the event with any Instrument it brought and its Transaction.

        A Transaction it no longer posts is deleted.
        """
        if self.new_instrument is not None:
            self.new_instrument.save()
            self.instance.instrument = self.new_instrument
        unposted = None
        if self.ledger is not None:
            self.instance.transaction = self.ledger.save()
        else:
            unposted, self.instance.transaction = self.instance.transaction, None
        event = super().save(commit=commit)
        if unposted is not None:
            unposted.delete()
        return event
