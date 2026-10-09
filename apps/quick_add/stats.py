"""What AI Quick Add has cost and how often its Drafts were right."""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from apps.quick_add.models import AICall, QuickAdd


@dataclass(frozen=True)
class AIStats:
    """The numbers on the Drafts page stats strip; cost is in USD."""

    total_cost: Decimal
    month_cost: Decimal
    quick_adds: int
    calls: int
    average_cost: Decimal
    # None until something is posted, since there is no share to show yet.
    posted_without_edits_percent: Decimal | None


def ai_stats() -> AIStats:
    """Cost in USD summed over every AI call, retries and failures included."""
    calls = AICall.objects.all()
    month_start = timezone.localdate().replace(day=1)
    total_cost = _cost(calls)
    quick_adds = QuickAdd.objects.count()
    return AIStats(
        total_cost=total_cost,
        month_cost=_cost(calls.filter(created_at__date__gte=month_start)),
        quick_adds=quick_adds,
        calls=calls.count(),
        average_cost=total_cost / quick_adds if quick_adds else Decimal(0),
        posted_without_edits_percent=_posted_without_edits_percent(),
    )


def _posted_without_edits_percent() -> Decimal | None:
    counts = QuickAdd.objects.filter(status=QuickAdd.Status.POSTED).aggregate(
        posted=Count("pk"), unedited=Count("pk", filter=Q(posted_without_edits=True))
    )
    posted: int = counts["posted"]
    unedited: int = counts["unedited"]
    return Decimal(100 * unedited) / posted if posted else None


def _cost(calls: QuerySet[AICall]) -> Decimal:
    return calls.aggregate(total=Sum("cost"))["total"] or Decimal(0)
