"""The morning job that keeps Velora ahead of the user's recurring money."""

from typing import TYPE_CHECKING

from apps.schedules.occurrences import materialise_occurrences, propose_due_drafts

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

# In order; each must be safe to run twice on the same day.
STEPS: tuple[Callable[[date], None], ...] = (
    materialise_occurrences,
    propose_due_drafts,
)


def run_daily_job(today: date) -> None:
    """Run every step for `today`, catching up any days the job did not run."""
    for step in STEPS:
        step(today)
