"""Turn a Draft into a Transaction, or drop it (ADR 0006)."""

from typing import Any

from django.db import transaction as db_transaction

from apps.classification.models import Party
from apps.quick_add.models import Draft, QuickAdd
from apps.transactions.models import Transaction
from apps.transactions.recording import TransactionForms


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


def form_data(draft: Draft, party: Party | None) -> dict[str, Any]:
    """The Draft as a submitted Transaction form, Split formset included."""
    splits = list(draft.splits.all())
    data: dict[str, Any] = {
        "date": draft.date.isoformat(),
        "party": party.pk if party else "",
        "description": draft.description,
        "splits-TOTAL_FORMS": len(splits),
        "splits-INITIAL_FORMS": 0,
    }
    for index, split in enumerate(splits):
        data |= {
            f"splits-{index}-from_account": split.from_account_id or "",
            f"splits-{index}-to_account": split.to_account_id or "",
            f"splits-{index}-amount": split.amount,
        }
    return data


def mark_posted(
    quick_add: QuickAdd, transaction: Transaction, *, without_edits: bool
) -> None:
    """Link the Quick Add to the Transaction its Draft became."""
    quick_add.status = QuickAdd.Status.POSTED
    quick_add.transaction = transaction
    quick_add.posted_without_edits = without_edits
    quick_add.failure_reason = ""
    quick_add.save(
        update_fields=[
            "status",
            "transaction",
            "posted_without_edits",
            "failure_reason",
        ]
    )


@db_transaction.atomic
def post_draft(quick_add: QuickAdd) -> Transaction:
    """Record the Draft as it is, checked by the Transaction form's rules."""
    draft = quick_add.draft
    forms = TransactionForms(form_data(draft, party_for(draft)), instance=Transaction())
    if not forms.is_valid():
        raise DraftNotPostableError(forms.errors())
    transaction = forms.save()
    mark_posted(quick_add, transaction, without_edits=True)
    return transaction
