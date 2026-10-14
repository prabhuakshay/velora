"""Forms for hand-entered Prices and Investment Events."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.utils import timezone

from apps.accounts.models import Account, AccountKind
from apps.investments.dividends import (
    income_account,
    linking,
    posts_dividend,
    save_unlinked,
)
from apps.investments.instrument_field import InstrumentField
from apps.investments.ledger import transaction_forms
from apps.investments.models import (
    NEEDS,
    Instrument,
    InvestmentEvent,
    Price,
    PriceSource,
)
from apps.investments.overselling import oversell_refusal
from apps.investments.replay import TRADES

if TYPE_CHECKING:
    import datetime

    from apps.transactions.models import Transaction
    from apps.transactions.recording import TransactionForms

REPLAYED = ("kind", "date", "units", "amount", "charges")
INSTRUMENT = InstrumentField()
NEW_INSTRUMENT = InstrumentField(
    "new_",
    label="New Instrument",
    help_text="For a Merger: the Instrument the units turn into.",
    creates_from_isin=False,
)


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
            defaults={
                "price": self.cleaned_data["price"],
                "source": PriceSource.MANUAL,
                "fetch": None,
                "entered_at": timezone.now(),
            },
        )
        return price


class EditPriceForm(forms.ModelForm[Price]):
    """Fix a Manual Price's day or value; it can't land on another Price's day."""

    class Meta:
        model = Price
        fields = ("date", "price")
        widgets: ClassVar = {"date": forms.DateInput(attrs={"type": "date"})}

    def clean_date(self) -> datetime.date:
        """Refuse a day after today or one that already has a Price."""
        when = _future_refused(self.cleaned_data["date"])
        others = Price.objects.filter(instrument=self.instance.instrument_id)
        if others.filter(date=when).exclude(pk=self.instance.pk).exists():
            message = "There's already a Price for that day."
            raise forms.ValidationError(message)
        return when

    def save(self, commit: bool = True) -> Price:  # noqa: FBT001, FBT002
        """Store the change as entered now."""
        self.instance.entered_at = timezone.now()
        return super().save(commit=commit)


def _future_refused(when: datetime.date) -> datetime.date:
    if when > timezone.localdate():
        message = "Pick today or earlier."
        raise forms.ValidationError(message)
    return when


OPTIONAL = ("units", "amount", "income_account")
REQUIRED = "This field is required."


def _same(a: Instrument, b: Instrument) -> bool:
    # Either may be unsaved, so compare what identifies an Instrument.
    return a.isin == b.isin and (a.isin is not None or a.name == b.name)


class InvestmentEventForm(forms.ModelForm[InvestmentEvent]):
    """Record or edit an Investment Event inside an Investment Account.

    The Instrument, and a Merger's new one, is an InstrumentField: a known
    one searched for or a new one added with the event. An event that would
    leave a Sell taking more units than held on its date, counting every
    other event, is refused. A Dividend also records its Income Transaction.
    Given a matched Transaction, the event is linked to it as it is instead.
    When drafting, the form only checks the event: its money is left to the
    Draft it is proposed as.
    """

    income_account = forms.ModelChoiceField(
        queryset=Account.objects.filter(kind=AccountKind.INCOME),
        required=False,
        help_text="For a Dividend: the Income Account it is recorded from.",
    )

    class Meta:
        model = InvestmentEvent
        fields = ("kind", "date", "units", "amount", "charges", "note")
        labels: ClassVar = {"kind": "Type"}
        help_texts: ClassVar = {
            "units": "For a Stock Split, the ratio: 5 when 1 unit becomes 5.",
            "amount": "The trade value before charges; or the Dividend paid.",
            "charges": "Brokerage, STT, stamp duty and other charges.",
        }
        widgets: ClassVar = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(
        self,
        *args: Any,  # noqa: ANN401
        account: Account,
        matched: Transaction | None = None,
        drafting: bool = False,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        super().__init__(*args, **kwargs)
        self.account = account
        self.matched = matched
        self.drafting = drafting
        self.instance.account = account
        self.fields |= INSTRUMENT.fields() | NEW_INSTRUMENT.fields()
        self.instrument_parts = INSTRUMENT.parts(self)
        self.new_instrument_parts = NEW_INSTRUMENT.parts(self)
        for name in ("units", "amount"):
            self.fields[name].widget.attrs["min"] = "0"
        if self.instance.pk:
            self.initial.update(INSTRUMENT.initial(self.instance.instrument))
            self.initial["income_account"] = income_account(self.instance.transaction)
            if (merged := self.instance.new_instrument) is not None:
                self.initial.update(NEW_INSTRUMENT.initial(merged))
        else:
            self.initial.setdefault("date", timezone.localdate())
        self.ledger: TransactionForms | None = None

    def clean_date(self) -> datetime.date:
        """Refuse a day after today."""
        return _future_refused(self.cleaned_data["date"])

    def clean(self) -> dict[str, Any]:
        """Check the kind's parts, find the Instruments, then replay every event."""
        super().clean()
        cleaned = self.cleaned_data
        self._keep_what_the_kind_needs()
        instrument = INSTRUMENT.resolve(self)
        if instrument is not None:
            self.instance.instrument = instrument
        self.instance.new_instrument = None
        if cleaned.get("kind") == InvestmentEvent.Kind.MERGER:
            self._merge_target(instrument)
        if not self.errors and instrument is not None:
            self._refuse_overselling(instrument)
            if not self.drafting:
                self._check_ledger(instrument)
        return cleaned

    def _keep_what_the_kind_needs(self) -> None:
        kind = self.cleaned_data.get("kind", "")
        needs = NEEDS.get(kind, ())
        if not self._posts_dividend():
            needs = tuple(name for name in needs if name != "income_account")
        if kind != InvestmentEvent.Kind.MERGER:
            self.cleaned_data |= NEW_INSTRUMENT.cleared()
        elif not NEW_INSTRUMENT.entered(self.cleaned_data):
            self.add_error("new_isin", REQUIRED)
        for name in OPTIONAL:
            if name not in needs:
                self.cleaned_data[name] = None
            elif self.cleaned_data.get(name) in (None, ""):
                self.add_error(name, REQUIRED)
        if kind not in TRADES:
            self.cleaned_data["charges"] = Decimal(0)

    def _posts_dividend(self) -> bool:
        """Whether a Dividend posts a Transaction it needs an Income Account for."""
        when = self.cleaned_data.get("date")
        return (
            self.matched is None
            and not self.drafting
            and when is not None
            and posts_dividend(
                InvestmentEvent(
                    account=self.account,
                    kind=self.cleaned_data.get("kind", ""),
                    date=when,
                )
            )
        )

    def _merge_target(self, instrument: Instrument | None) -> None:
        if self.has_error("new_isin"):
            return
        kind = instrument.kind if instrument else Instrument.Kind.STOCK
        target = NEW_INSTRUMENT.resolve(self, default_kind=kind)
        if target is None:
            return
        if instrument is not None and _same(target, instrument):
            searched = self.cleaned_data.get("new_instrument")
            field = "new_instrument" if searched else "new_isin"
            self.add_error(field, "Pick a different Instrument to merge into.")
        else:
            self.instance.new_instrument = target

    def _candidate(self, instrument: Instrument) -> InvestmentEvent:
        # The instance only takes the form's values after clean(), so use a copy.
        return InvestmentEvent(
            account=self.account,
            instrument=instrument,
            new_instrument=self.instance.new_instrument,
            transaction=self.instance.transaction,
            **{name: self.cleaned_data[name] for name in REPLAYED},
        )

    def _refuse_overselling(self, instrument: Instrument) -> None:
        if refusal := oversell_refusal(
            self.account,
            adding=self._candidate(instrument),
            leaving_out=self.instance.pk,
            with_drafts=self.drafting,
        ):
            raise forms.ValidationError(refusal)

    def _check_ledger(self, instrument: Instrument) -> None:
        if self.matched is not None:
            self.ledger = None
        else:
            self.ledger = transaction_forms(
                self._candidate(instrument), self.cleaned_data["income_account"]
            )
        if self.ledger is not None and not self.ledger.is_valid():
            for error in self.ledger.errors():
                self.add_error(None, error)

    def save(self, commit: bool = True) -> InvestmentEvent:  # noqa: FBT001, FBT002
        """Save the event, any Instrument it brought and its Transaction."""
        InstrumentField.save_if_new(self.instance.instrument)
        InstrumentField.save_if_new(self.instance.new_instrument)
        event = super().save(commit=False)
        if commit:
            if self.matched is not None:
                event.transaction = self.matched
                event.save()
            elif self.ledger is None:
                save_unlinked(event)
            else:
                self.ledger.save(within=linking(event, self.ledger))
        return event
