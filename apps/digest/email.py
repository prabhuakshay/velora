"""The morning digest email, sent as the daily job's last step."""

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.template.loader import render_to_string

from apps.digest.models import Digest
from apps.digest.upcoming import upcoming
from apps.users.models import User

if TYPE_CHECKING:
    from datetime import date


@db_transaction.atomic
def send_digest(today: date) -> None:
    """Email today's Upcoming items to the user (ADR 0001), once a day.

    Nothing is sent when there is nothing to report. A failed send rolls back
    the day's record, so running the job again that day sends it.
    """
    sections = upcoming(today)
    if not sections:
        return
    _, created = Digest.objects.get_or_create(sent_on=today)
    if not created:
        return
    for user in User.objects.filter(is_active=True):
        body = render_to_string(
            "digest/digest_email.txt",
            {
                "user": user,
                "today": today,
                "sections": sections,
                "site_url": settings.SITE_URL,
            },
        )
        send_mail(
            f"{settings.EMAIL_SUBJECT_PREFIX}Your digest for {today:%-d %b %Y}",
            body,
            None,
            [user.email],
        )
