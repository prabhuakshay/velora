"""The morning digest email, sent as the daily job's last step."""

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forecast import Item
from apps.budgets.warnings import due_warnings, record_budget_warnings
from apps.digest.models import Digest
from apps.digest.upcoming import Section, upcoming
from apps.investments.fetches import failed_nightly
from apps.users.models import User

if TYPE_CHECKING:
    from datetime import date


def send_digest(today: date) -> None:
    """Email today's Upcoming items to each user (ADR 0001), once a day.

    Nothing is sent when there is nothing to report. A failed send rolls back
    that user's record for the day, so running the job again that day sends
    it to them, and only them.
    """
    warned = due_warnings(today)
    sections = upcoming(today, warned)
    if failures := _price_fetch_failures():
        sections.append(failures)
    if not sections:
        return
    sent = False
    for user in User.objects.filter(is_active=True):
        with db_transaction.atomic():
            _, created = Digest.objects.get_or_create(sent_on=today, user=user)
            if created:
                _send(user, today, sections)
                sent = True
    if sent:
        record_budget_warnings(warned, today)


def _price_fetch_failures() -> Section | None:
    """A line per source whose latest nightly Price Fetch failed, if any.

    Only the digest says this: the investments overview has its own banner.
    """
    items = [
        Item(
            timezone.localdate(fetch.started_at),
            f"{fetch.source} Price Fetch failed: {fetch.reason}",
            None,
            reverse("investments_overview"),
        )
        for fetch in failed_nightly()
    ]
    return Section("Price Fetches", items, amounts=False) if items else None


def _send(user: User, today: date, sections: list[Section]) -> None:
    context = {
        "user": user,
        "today": today,
        "sections": sections,
        "site_url": settings.SITE_URL,
    }
    send_mail(
        f"{settings.EMAIL_SUBJECT_PREFIX}Your digest for {today:%-d %b %Y}",
        render_to_string("digest/digest_email.txt", context),
        None,
        [user.email],
        html_message=render_to_string("digest/digest_email.html", context),
    )
