"""Propose due Schedules' Drafts now instead of waiting for the daily job."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.schedules.matching import match_transactions
from apps.schedules.occurrences import materialise_occurrences, propose_due_drafts


class Command(BaseCommand):
    """Run only the daily job's Draft steps, so no digest email goes out."""

    help = "Propose a Draft for every Schedule Occurrence due by today."

    def handle(self, *_args: object, **_options: object) -> None:
        """Lay out Occurrences, match recorded Transactions, then propose Drafts."""
        today = timezone.localdate()
        materialise_occurrences(today)
        match_transactions(today)
        propose_due_drafts(today)
