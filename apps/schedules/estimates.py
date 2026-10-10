"""What an open-amount Schedule is expected to cost, from what was paid before."""

from typing import TYPE_CHECKING

from apps.transactions.models import Split

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from apps.schedules.models import ScheduleSplit


def last_paid_amount(split: ScheduleSplit, on: date) -> Decimal | None:
    """The latest amount paid between its Accounts by `on`, to its Party if any."""
    paid = Split.objects.filter(
        from_account=split.from_account_id,
        to_account=split.to_account_id,
        transaction__date__lte=on,
    )
    if split.schedule.party_id:
        paid = paid.filter(transaction__party=split.schedule.party_id)
    latest = paid.order_by("-transaction__date", "-pk").first()
    return latest.amount if latest else None
