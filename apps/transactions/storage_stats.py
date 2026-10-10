"""How much Attachment storage Velora's records say is used, and by what."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.db.models import Case, Count, F, Min, Sum, Value, When
from django.db.models.functions import TruncMonth
from django.utils import dateformat, timezone

from apps.transactions.models import Attachment, Transaction


@dataclass(frozen=True)
class Share:
    """A slice of Attachment storage: how many Attachments and their size."""

    label: str
    count: int
    size: int


@dataclass(frozen=True)
class AttachmentStorageStats:
    """The figures on the Storage page; sizes are in bytes."""

    total_size: int
    attachments: int
    transactions: int
    # None while there are no Attachments, shown as a dash.
    average_size: int | None
    oldest: datetime | None
    file_types: list[Share]
    largest_attachments: list[Attachment]
    # Annotated with attachment_count and attachment_size.
    largest_transactions: list[Transaction]
    transaction_years: list[Share]
    # The last 12 months by Attachment creation time, newest first, empty
    # months included unless all are.
    recent_months: list[Share]


FILE_TYPE_GROUPS = ("Images", "PDF", "Other")
LARGEST_LIMIT = 10
RECENT_MONTHS = 12


def _file_type_shares() -> list[Share]:
    group = Case(
        When(content_type__startswith="image/", then=Value("Images")),
        When(content_type="application/pdf", then=Value("PDF")),
        default=Value("Other"),
    )
    rows = {
        row["group"]: Share(row["group"], row["count"], row["size"])
        for row in Attachment.objects.order_by()
        .annotate(group=group)
        .values("group")
        .annotate(count=Count("pk"), size=Sum("size"))
    }
    return [rows[label] for label in FILE_TYPE_GROUPS if label in rows]


def _recent_month_shares() -> list[Share]:
    month = timezone.localdate().replace(day=1)
    months = [month]
    for _ in range(RECENT_MONTHS - 1):
        month = (month - timedelta(days=1)).replace(day=1)
        months.append(month)
    window_start = timezone.make_aware(datetime.combine(months[-1], time.min))
    rows = {
        row["month"].date(): row
        for row in Attachment.objects.order_by()
        .filter(created_at__gte=window_start)
        .values(month=TruncMonth("created_at"))
        .annotate(count=Count("pk"), size=Sum("size"))
    }
    if not rows:
        return []
    return [
        Share(
            dateformat.format(month, "M Y"),
            rows[month]["count"] if month in rows else 0,
            rows[month]["size"] if month in rows else 0,
        )
        for month in months
    ]


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
        file_types=_file_type_shares(),
        largest_attachments=list(
            Attachment.objects.select_related("transaction__party").order_by(
                "-size", "pk"
            )[:LARGEST_LIMIT]
        ),
        largest_transactions=list(
            Transaction.objects.select_related("party")
            .filter(attachments__isnull=False)
            .annotate(
                attachment_count=Count("attachments"),
                attachment_size=Sum("attachments__size"),
            )
            .order_by("-attachment_size", "pk")[:LARGEST_LIMIT]
        ),
        transaction_years=[
            Share(str(row["year"]), row["count"], row["size"])
            for row in Attachment.objects.order_by()
            .values(year=F("transaction__date__year"))
            .annotate(count=Count("pk"), size=Sum("size"))
            .order_by("-year")
        ],
        recent_months=_recent_month_shares(),
    )
