"""Merge one Party or Tag into another of the same type."""

from typing import TYPE_CHECKING

from django.db import transaction as db_transaction

if TYPE_CHECKING:
    from apps.classification.models import Party, Tag


def merge_party(source: Party, target: Party) -> None:
    """Point every Transaction of the source at the target, then remove it.

    Saves row by row, not with update(), so change history records each one.
    """
    reason = f"Merged {source} into {target}"
    with db_transaction.atomic():
        for transaction in source.transactions.all():
            transaction.party = target
            transaction._change_reason = reason  # type: ignore[attr-defined]  # noqa: SLF001
            transaction.save()
        source._change_reason = reason  # type: ignore[attr-defined]  # noqa: SLF001
        source.delete()


def merge_tag(source: Tag, target: Tag) -> None:
    """Put the target on every Split carrying the source, then remove it.

    Changes each Split's Tags rather than letting the delete drop them, so
    Split change history records the swap.
    """
    reason = f"Merged {source} into {target}"
    with db_transaction.atomic():
        for split in source.splits.all():
            split._change_reason = reason  # type: ignore[attr-defined]  # noqa: SLF001
            split.tags.add(target)
            split.tags.remove(source)
        source._change_reason = reason  # type: ignore[attr-defined]  # noqa: SLF001
        source.delete()
