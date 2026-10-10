from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.schedules.models import Schedule

if TYPE_CHECKING:
    from apps.accounts.models import Account


def make_schedule(
    *splits: tuple[Account, Account, str | None], **fields: Any
) -> Schedule:
    """An active Schedule due monthly from 5 Oct 2026, with the given Splits."""
    schedule = Schedule.objects.create(
        **{"start_date": date(2026, 10, 5), "every": 1, "unit": "month", **fields}
    )
    for source, destination, amount in splits:
        schedule.splits.create(
            from_account=source,
            to_account=destination,
            amount=Decimal(amount) if amount else None,
        )
    return schedule


def schedule_form_data(
    *splits: tuple[Account, Account, str], **fields: Any
) -> dict[str, Any]:
    """The Schedule form as posted, monthly from 5 Oct 2026."""
    data: dict[str, Any] = {
        "party": "",
        "description": "Flat rent",
        "start_date": "2026-10-05",
        "every": 1,
        "unit": "month",
        "ends_on": "",
        "ends_after": "",
        "cron": "",
        "grace_days": 3,
        "reminder_days": 3,
        "splits-TOTAL_FORMS": len(splits),
        "splits-INITIAL_FORMS": 0,
        **fields,
    }
    for index, (source, destination, amount) in enumerate(splits):
        data |= {
            f"splits-{index}-from_account": source.pk,
            f"splits-{index}-to_account": destination.pk,
            f"splits-{index}-amount": amount,
        }
    return data
