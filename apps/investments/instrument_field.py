"""The Instrument field: search the known Instruments, or add a new one.

A form adds the field's parts under names of its own, so it can hold two, as
an Investment Event does for a Merger. The search box takes an ISIN or an
exact name; the script under assets fills it from the matches as you type.
Add new, taking a name, a kind and an optional ISIN, wins over the search.
With neither, the ISIN and name are read the older way the CSV import still
posts them: a known ISIN, or a name picking or creating an Instrument without
one. Which Instrument each way picks is up to apps.investments.instruments.
"""

from dataclasses import dataclass
from typing import Any

from django import forms

from apps.investments import instruments
from apps.investments.instruments import Refusal
from apps.investments.isin import is_valid_isin
from apps.investments.models import Instrument

INVALID_ISIN = (
    "This isn't a valid ISIN. For an Instrument without one, leave the ISIN "
    "blank and enter its name."
)
# Where each Refusal shows; the rest show on the new Instrument's name.
SHOWN_ON = {Refusal.NO_MATCH: "search", Refusal.NOT_KNOWN: "isin"}


class IsinField(forms.CharField):
    """A blank or real ISIN, kept in capitals."""

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(max_length=12, required=False, **kwargs)

    def to_python(self, value: Any) -> str:  # noqa: ANN401
        """Capitals, refused unless a real ISIN."""
        isin = (super().to_python(value) or "").upper()
        if isin and not is_valid_isin(isin):
            raise forms.ValidationError(INVALID_ISIN)
        return isin


@dataclass(frozen=True)
class InstrumentField:
    """One Instrument field's parts, named from a prefix, and how to read them.

    An unknown ISIN posted the older way is created under the posted name, or,
    without creates_from_isin, refused on the ISIN.
    """

    prefix: str = ""
    label: str = "Instrument"
    help_text: str = ""
    creates_from_isin: bool = True

    @property
    def search(self) -> str:
        """The search box's name."""
        return f"{self.prefix}instrument"

    @property
    def add_new(self) -> str:
        """The Add new checkbox's name."""
        return f"{self.prefix}add_new"

    @property
    def isin(self) -> str:
        """The ISIN's name."""
        return f"{self.prefix}isin"

    @property
    def name(self) -> str:
        """The new Instrument's name's name."""
        return f"{self.prefix}instrument_name"

    @property
    def kind(self) -> str:
        """The new Instrument's kind's name."""
        return f"{self.prefix}instrument_kind"

    @staticmethod
    def save_if_new(instrument: Instrument | None) -> None:
        """Save an Instrument resolve() added, before what refers to it."""
        instruments.save_if_new(instrument)

    def parts(self, form: forms.BaseForm) -> dict[str, forms.BoundField]:
        """The form's bound parts, by role, for the template to lay out."""
        return {
            "search": form[self.search],
            "add_new": form[self.add_new],
            "isin": form[self.isin],
            "name": form[self.name],
            "kind": form[self.kind],
        }

    def fields(self) -> dict[str, forms.Field]:
        """The form fields, to add to a form's own."""
        return {
            self.search: forms.CharField(
                label=self.label,
                max_length=200,
                required=False,
                help_text=self.help_text or "Its name or ISIN.",
                widget=forms.TextInput(
                    attrs={"autocomplete": "off", "data-instrument-query": ""}
                ),
            ),
            self.add_new: forms.BooleanField(
                label="Add a new Instrument", required=False
            ),
            self.name: forms.CharField(
                label="Name",
                max_length=200,
                required=False,
                widget=forms.TextInput(attrs={"data-instrument-name": ""}),
            ),
            self.kind: forms.ChoiceField(
                label="Type",
                choices=Instrument.Kind.choices,
                initial=Instrument.Kind.STOCK,
                required=False,
            ),
            self.isin: IsinField(
                label="ISIN", help_text="Leave it blank for an Instrument without one."
            ),
        }

    def initial(self, instrument: Instrument) -> dict[str, Any]:
        """What the field starts from when editing something on this Instrument."""
        return {
            self.search: instrument.isin or instrument.name,
            self.isin: instrument.isin,
            self.name: instrument.name,
        }

    def cleared(self) -> dict[str, Any]:
        """The parts emptied, for a form that doesn't need this Instrument."""
        return {self.search: "", self.add_new: False, self.isin: "", self.name: ""}

    def entered(self, cleaned: dict[str, Any]) -> bool:
        """Whether any way of picking an Instrument was used."""
        return any(
            cleaned.get(name)
            for name in (self.search, self.add_new, self.isin, self.name)
        )

    def resolve(
        self,
        form: forms.BaseForm,
        default_kind: str = Instrument.Kind.STOCK,
    ) -> Instrument | None:
        """The Instrument picked, unsaved when new; None with the form's errors."""
        cleaned = form.cleaned_data
        if self.isin not in cleaned:
            return None
        text = cleaned.get(self.search, "").strip()
        isin, name = cleaned[self.isin], cleaned.get(self.name, "")
        kind = cleaned.get(self.kind) or default_kind
        if cleaned.get(self.add_new):
            picked = instruments.add(isin, name, kind)
        elif text:
            picked = instruments.find(text)
        else:
            picked = instruments.pick(
                isin, name, kind, creates_from_isin=self.creates_from_isin
            )
        if isinstance(picked, Refusal):
            form.add_error(getattr(self, SHOWN_ON.get(picked, "name")), picked)
            return None
        return picked
