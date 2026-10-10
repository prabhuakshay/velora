"""Keeping Occurrences open when the Transaction covering them goes."""

from typing import TYPE_CHECKING

from apps.quick_add.models import Draft
from apps.schedules.models import Occurrence

if TYPE_CHECKING:
    from apps.transactions.models import Transaction


def reopen_occurrence(instance: Transaction, **_: object) -> None:
    """Put the Occurrence the deleted Transaction covered back to Upcoming.

    The next daily job then matches it again, proposes a Draft or marks it
    Missed. The Draft that posted the Transaction is removed, so a new one
    can be proposed for the Occurrence.
    """
    Draft.objects.filter(occurrence__transaction=instance).delete()
    Occurrence.objects.filter(transaction=instance).update(
        status=Occurrence.Status.UPCOMING, transaction=None
    )
