"""Which Instrument an ISIN or name picks, and adding one (ADR 0017).

An Instrument with an ISIN is that ISIN; one without is its name, in any
case. Every place that looks up or adds an Instrument goes through here, so
forms, the Investment Import and the search agree on what is the same
Instrument. A new Instrument comes back unsaved, for the caller to save once
nothing refuses it.
"""

from enum import StrEnum

from django.db.models import Q, QuerySet

from apps.investments.isin import is_valid_isin
from apps.investments.models import Instrument

MATCHES = 10


class Refusal(StrEnum):
    """Why no Instrument could be picked or added."""

    NO_MATCH = "No Instrument matches this. Pick one from the list, or add a new one."
    NO_NAME = "Enter the new Instrument's name."
    TAKEN = "There's already an Instrument without an ISIN named this; pick it instead."
    NOT_KNOWN = "Velora doesn't know this ISIN."
    UNKNOWN_ISIN = "Velora doesn't know this ISIN; enter the Instrument's name."
    NO_ISIN = "Enter the ISIN, or the name of an Instrument without one."


def matches(query: str) -> QuerySet[Instrument]:
    """The first Instruments whose name has the query or whose ISIN starts with it."""
    query = query.strip()
    if not query:
        return Instrument.objects.none()
    return Instrument.objects.filter(
        Q(name__icontains=query) | Q(isin__istartswith=query)
    ).order_by("name")[:MATCHES]


def find(text: str) -> Instrument | Refusal:
    """The Instrument a full ISIN or an exact name picks, if just one."""
    text = text.strip()
    if is_valid_isin(text.upper()):
        found = Instrument.objects.filter(isin=text.upper()).first()
        return found or Refusal.NO_MATCH
    named = Instrument.objects.filter(name__iexact=text)
    if (without_isin := named.filter(isin=None).first()) is not None:
        return without_isin
    return named.get() if named.count() == 1 else Refusal.NO_MATCH


def add(isin: str, name: str, kind: str) -> Instrument | Refusal:
    """The Instrument the user adds: the known one for a known ISIN, else new."""
    if isin and (known := _with_isin(isin)) is not None:
        return known
    name = name.strip()
    if not name:
        return Refusal.NO_NAME
    if not isin and _without_isin(name) is not None:
        return Refusal.TAKEN
    return Instrument(isin=isin or None, name=name, kind=kind)


def pick(
    isin: str, name: str, kind: str, *, creates_from_isin: bool
) -> Instrument | Refusal:
    """The Instrument an ISIN and name pick, the older way the import posts them.

    A known ISIN, or a name without one, picks the Instrument; an unknown ISIN
    with a name adds it, unless creates_from_isin is off.
    """
    name = name.strip()
    if (known := _with_isin(isin) if isin else _without_isin(name)) is not None:
        return known
    if isin and not creates_from_isin:
        return Refusal.NOT_KNOWN
    if not name:
        return Refusal.UNKNOWN_ISIN if isin else Refusal.NO_ISIN
    return Instrument(isin=isin or None, name=name, kind=kind)


def same(a: Instrument, b: Instrument) -> bool:
    """Whether two Instruments, either maybe unsaved, are the same one."""
    return a.isin == b.isin and (
        a.isin is not None or a.name.casefold() == b.name.casefold()
    )


def matching(isin: str, name: str, prefix: str = "") -> Q:
    """A filter for the Instrument an ISIN, or else a name, identifies.

    The prefix reaches it through a relation, such as "instrument__".
    """
    if isin:
        return Q(**{f"{prefix}isin": isin.upper()})
    return Q(**{f"{prefix}isin": None, f"{prefix}name__iexact": name.strip()})


def save_if_new(instrument: Instrument | None) -> None:
    """Save an Instrument add() or pick() made, before what refers to it."""
    if instrument is not None and not instrument.pk:
        instrument.save()


def _with_isin(isin: str) -> Instrument | None:
    return Instrument.objects.filter(isin=isin).first()


def _without_isin(name: str) -> Instrument | None:
    return Instrument.objects.filter(matching("", name)).first()
