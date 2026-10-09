"""Helpers for change history."""

from django.db.models import Model
from django.utils.text import Truncator

# simple_history's default history_change_reason column length.
REASON_MAX_LENGTH = 100


def with_reason[M: Model](record: M, reason: str) -> M:
    """Set the reason change history records for the record's next change."""
    reason = Truncator(reason).chars(REASON_MAX_LENGTH)
    record._change_reason = reason  # type: ignore[attr-defined]  # noqa: SLF001
    return record
