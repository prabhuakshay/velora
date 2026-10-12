"""Keeping Occurrences open when the Transaction covering them goes."""

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence
from apps.schedules.occurrences import propose_draft

if TYPE_CHECKING:
    from apps.transactions.models import Transaction


def reopen_occurrence(instance: Transaction, **_: object) -> None:
    """Give the Occurrence the deleted Transaction covered a waiting Draft.

    The Draft that posted the Transaction is removed and a new one proposed,
    never auto-posted, so the user decides whether the due date was paid.
    Rejecting the Draft is how they Skip it.
    """
    Draft.objects.filter(occurrence__transaction=instance).delete()
    reopened = list(Occurrence.objects.filter(transaction=instance))
    Occurrence.objects.filter(pk__in=[occurrence.pk for occurrence in reopened]).update(
        status=Occurrence.Status.UPCOMING, transaction=None
    )
    for occurrence in reopened:
        propose_draft(occurrence, timezone.localdate(), auto_post=False)
