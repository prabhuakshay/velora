"""Merge or delete Parties and Tags, recording each change in history."""

from typing import TYPE_CHECKING

from django.db import transaction as db_transaction

from apps.core.history import with_reason

if TYPE_CHECKING:
    from apps.classification.models import Party, Tag


def merge_party(source: Party, target: Party) -> None:
    """Point every Transaction and Draft of the source at the target, then remove it.

    Saves Transactions row by row, not with update(), so change history
    records each one; Drafts keep no history.
    """
    reason = f"Merged {source} into {target}"
    with db_transaction.atomic():
        for transaction in source.transactions.all():
            transaction.party = target
            with_reason(transaction, reason).save()
        source.drafts.update(party=target)
        with_reason(source, reason).delete()


def merge_tag(source: Tag, target: Tag) -> None:
    """Put the target on every Split carrying the source, then remove it.

    Changes each Split's Tags rather than letting the delete drop them, so
    Split change history records the swap.
    """
    reason = f"Merged {source} into {target}"
    with db_transaction.atomic():
        for split in source.splits.all():
            with_reason(split, reason)
            split.tags.add(target)
            split.tags.remove(source)
        with_reason(source, reason).delete()


def delete_tag(tag: Tag) -> None:
    """Take the Tag off every Split carrying it, then remove it.

    Like merge_tag, changes each Split so Split change history records it.
    """
    reason = f"Deleted {tag}"
    with db_transaction.atomic():
        for split in tag.splits.all():
            with_reason(split, reason).tags.remove(tag)
        with_reason(tag, reason).delete()
