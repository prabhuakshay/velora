"""The morning job that keeps every Schedule, Statement and Card EMI up to date."""

from typing import TYPE_CHECKING

from apps.cards.emis import propose_card_emi_drafts
from apps.cards.statements import create_statements, match_card_payments
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


def run_daily_job(today: date) -> None:
    """Run every step for `today`, catching up any days the job did not run."""
    for step in STEPS:
        step(today)
