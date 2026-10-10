"""How much Attachment storage Velora's records say is used, and by what."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Count, Min, Sum

from apps.transactions.models import Attachment

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class AttachmentStorageStats:
    """The figures on the Storage page; sizes are in bytes."""

    total_size: int
    attachments: int
    transactions: int
    # None while there are no Attachments, shown as a dash.
    average_size: int | None
    oldest: datetime | None


def attachment_storage_stats() -> AttachmentStorageStats:
    """Figures computed from every Attachment row."""
    totals = Attachment.objects.aggregate(
        total_size=Sum("size"),
        attachments=Count("pk"),
        transactions=Count("transaction", distinct=True),
        oldest=Min("created_at"),
    )
    total_size: int = totals["total_size"] or 0
    attachments: int = totals["attachments"]
    return AttachmentStorageStats(
        total_size=total_size,
        attachments=attachments,
        transactions=totals["transactions"],
        average_size=total_size // attachments if attachments else None,
        oldest=totals["oldest"],
    )
