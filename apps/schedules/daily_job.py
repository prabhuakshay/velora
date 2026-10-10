"""The morning job that keeps every Schedule, Statement and Card EMI up to date."""

import logging
import traceback
from typing import TYPE_CHECKING

from django.core.mail import mail_admins

from apps.cards.emis import propose_card_emi_drafts
from apps.cards.statements import create_statements, match_card_payments
from apps.core.jobs import ItemsFailedError
from apps.digest.email import send_digest
from apps.schedules.matching import mark_missed, match_transactions
from apps.schedules.occurrences import materialise_occurrences, propose_due_drafts
from apps.schedules.suggestions import suggest_schedules

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

# In order; each must be safe to run twice on the same day.
STEPS: tuple[Callable[[date], None], ...] = (
    materialise_occurrences,
    # Match first, so a Transaction already recorded needs no Draft.
    match_transactions,
    propose_due_drafts,
    mark_missed,
    # Settle payments first, so a new Statement's estimate leaves them out.
    match_card_payments,
    create_statements,
    propose_card_emi_drafts,
    suggest_schedules,
    # Last, so the digest reports what every other step left.
    send_digest,
)


logger = logging.getLogger("daily_job")


class DailyJobError(Exception):
    """Some steps failed; each failure is already logged and emailed."""


def run_daily_job(today: date) -> None:
    """Run every step for `today`, catching up due dates still within grace.

    A failed step does not stop the later ones. The job raises afterwards, so
    it shows as failed; the next run catches up. The admins get one email
    for the whole run, so a system-wide fault does not flood their inbox.
    """
    failed_steps, reports = [], []
    for step in STEPS:
        try:
            step(today)
        except ItemsFailedError as error:
            failed_steps.append(step.__name__)
            reports.extend(error.failures)
        except Exception:
            logger.exception("%s failed", step.__name__)
            failed_steps.append(step.__name__)
            reports.append(f"{step.__name__} failed\n{traceback.format_exc()}")
    if failed_steps:
        try:
            mail_admins(
                f"Daily job failed: {', '.join(failed_steps)}", "\n\n".join(reports)
            )
        except Exception:
            logger.exception("Emailing the admins failed")
        raise DailyJobError(", ".join(failed_steps))
