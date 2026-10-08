from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from apps.users.models import User


def update_last_login_without_history(user: User, **_: object) -> None:
    # Every login bumps last_login; that is not a change worth a history row.
    user.last_login = timezone.now()
    user.save_without_historical_record(update_fields=["last_login"])
