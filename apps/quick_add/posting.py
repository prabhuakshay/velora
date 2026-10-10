"""Turn a Draft into a Transaction, or drop it (ADR 0006)."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from django.db import transaction as db_transaction
from django.utils import timezone

from apps.classification.models import Party
from apps.quick_add.models import Draft
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms

if TYPE_CHECKING:
    from collections.abc import Iterator


class DraftNotPostableError(Exception):
    """The Draft no longer passes the Transaction rules against current data."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__(" ".join(reasons))
        self.reasons = reasons


def party_named(name: str) -> Party:
    """The Party with this name, ignoring case, created if there is none."""
    party, _ = Party.objects.get_or_create(name__iexact=name, defaults={"name": name})
    return party


def party_for(draft: Draft) -> Party | None:
    """The Draft's Party, creating the new one it names unless one matches."""
    if not draft.new_party_name:
        return draft.party
    return party_named(draft.new_party_name)


def matching_party(draft: Draft) -> Party | None:
    """The Draft's Party, or the existing one its new name matches."""
    if not draft.new_party_name:
        return draft.party
    return Party.objects.filter(name__iexact=draft.new_party_name).first()


def missing_parts(draft: Draft) -> list[str]:
    """What the Draft still lacks before it can be posted; empty when nothing."""
    splits = list(draft.splits.all())
    if not splits:
        return ["Add at least one Split."]
    missing = []
    for number, split in enumerate(splits, start=1):
        gaps = [
            ("From Account", split.from_account_id),
            ("To Account", split.to_account_id),
            ("amount", split.amount),
        ]
        missing += [
            f"Split {number}: missing {what}." for what, value in gaps if value is None
        ]
    return missing


def form_data(draft: Draft, party: Party | None) -> dict[str, Any]:
    """The Draft as a submitted Transaction form, Split formset included."""
    splits = list(draft.splits.all())
    data: dict[str, Any] = {
        # A Draft may wait for a day yet to come; posted early, it happens today.
        "date": min(draft.date, timezone.localdate()).isoformat(),
        "party": party.pk if party else "",
        "description": draft.description,
        "splits-TOTAL_FORMS": len(splits),
        "splits-INITIAL_FORMS": 0,
    }
    for index, split in enumerate(splits):
        data |= {
            f"splits-{index}-from_account": split.from_account_id or "",
            f"splits-{index}-to_account": split.to_account_id or "",
            f"splits-{index}-amount": "" if split.amount is None else split.amount,
        }
    return data


class DraftGoneError(Exception):
    """The Draft was posted or rejected by another request meanwhile."""


@contextmanager
def posting_edited(
    draft: Draft, transaction: Transaction, new_party_name: str
) -> Iterator[None]:
    """Wrap saving the edited Transaction so the Draft is posted with it.

    Run inside the save's database transaction: the Draft is locked and
    checked to still be waiting, so it is posted once, and the new Party is
    created only if the Transaction is saved.
    """
    locked = Draft.objects.select_for_update().get(pk=draft.pk)
    if locked.status != Draft.Status.WAITING:
        raise DraftGoneError
    if new_party_name and transaction.party is None:
        transaction.party = party_named(new_party_name)
    yield
    locked.mark_posted(transaction, without_edits=False)


@db_transaction.atomic
def post_draft(draft: Draft) -> Transaction:
    """Record the Draft as it is, checked by the Transaction form's rules."""
    if missing := missing_parts(draft):
        raise DraftNotPostableError(missing)
    forms = TransactionForms(form_data(draft, party_for(draft)), instance=Transaction())
    if not forms.is_valid():
        raise DraftNotPostableError(forms.errors())
    transaction = forms.save()
    draft.mark_posted(transaction, without_edits=True)
    return transaction
