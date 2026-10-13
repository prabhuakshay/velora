"""The form for entering an Instrument's Price by hand."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django import forms
from django.utils import timezone

from apps.investments.models import Instrument, Price

if TYPE_CHECKING:
    import datetime


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
