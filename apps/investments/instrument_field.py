"""The Instrument field: search the known Instruments, or add a new one.

A form adds the field's parts under names of its own, so it can hold two, as
an Investment Event does for a Merger. The search box takes an ISIN or an
exact name; the script under assets fills it from the matches as you type.
Add new, taking a name, a kind and an optional ISIN, wins over the search.
With neither, the ISIN and name are read the older way the CSV import still
posts them: a known ISIN, or a name picking or creating an Instrument without
one.
"""

from dataclasses import dataclass
from typing import Any

from django import forms
from django.db.models import Q, QuerySet

from apps.investments.isin import is_valid_isin
from apps.investments.models import Instrument

INVALID_ISIN = (
    "This isn't a valid ISIN. For an Instrument without one, leave the ISIN "
    "blank and enter its name."
)
UNKNOWN_ISIN = "Velora doesn't know this ISIN; enter the Instrument's name."
NOT_KNOWN = "Velora doesn't know this ISIN."
NO_ISIN = "Enter the ISIN, or the name of an Instrument without one."
NO_MATCH = "No Instrument matches this. Pick one from the list, or add a new one."
NO_NAME = "Enter the new Instrument's name."
TAKEN = "There's already an Instrument without an ISIN named this; pick it instead."
MATCHES = 10


def matches(query: str) -> QuerySet[Instrument]:
    """The first Instruments whose name has the query or whose ISIN starts with it."""
    query = query.strip()
    if not query:
        return Instrument.objects.none()
    return Instrument.objects.filter(
        Q(name__icontains=query) | Q(isin__istartswith=query)
    ).order_by("name")[:MATCHES]


def find(text: str) -> Instrument | None:
    """The Instrument a full ISIN or an exact name picks, if just one."""
    if is_valid_isin(text.upper()):
        return Instrument.objects.filter(isin=text.upper()).first()
    named = Instrument.objects.filter(name__iexact=text)
    without_isin = named.filter(isin=None).first()
    if without_isin is not None:
        return without_isin
    return named.first() if named.count() == 1 else None


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
        if instrument is not None and not instrument.pk:
            instrument.save()

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
        adding = cleaned.get(self.add_new)
        text = cleaned.get(self.search, "").strip()
        if text and not adding:
            return find(text) or _refused(form, self.search, NO_MATCH)
        isin = cleaned[self.isin]
        if isin and (known := Instrument.objects.filter(isin=isin).first()):
            return known
        name = cleaned.get(self.name, "").strip()
        new = Instrument(
            isin=isin or None, name=name, kind=cleaned.get(self.kind) or default_kind
        )
        return (self._added if adding else self._posted)(form, new)

    def _added(self, form: forms.BaseForm, new: Instrument) -> Instrument | None:
        if not new.name:
            return _refused(form, self.name, NO_NAME)
        if new.isin is None and _without_isin(new.name) is not None:
            return _refused(form, self.name, TAKEN)
        return new

    def _posted(self, form: forms.BaseForm, new: Instrument) -> Instrument | None:
        if new.isin and not self.creates_from_isin:
            return _refused(form, self.isin, NOT_KNOWN)
        if new.isin is None and (named := _without_isin(new.name)) is not None:
            return named
        if not new.name:
            return _refused(form, self.name, UNKNOWN_ISIN if new.isin else NO_ISIN)
        return new


def _without_isin(name: str) -> Instrument | None:
    return Instrument.objects.filter(isin=None, name__iexact=name).first()


def _refused(form: forms.BaseForm, field: str, message: str) -> Instrument | None:
    form.add_error(field, message)
    return None
