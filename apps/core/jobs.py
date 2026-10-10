"""Keeping one failure in the daily job from stopping the rest of it."""

import logging
import traceback
from typing import TYPE_CHECKING

from django.db import transaction as db_transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from django.db.models import Model

logger = logging.getLogger("daily_job")


class ItemsFailedError(Exception):
    """Some of a step's items failed; each is already logged."""

    def __init__(self, step: str, failures: list[str]) -> None:
        super().__init__(step)
        self.failures = failures


def run_each[T: Model](
    step: str, items: Iterable[T], action: Callable[[T], object]
) -> None:
    """Run the action on each item, rolling back only the items that fail."""
    failures = []
    for item in items:
        try:
            with db_transaction.atomic():
                action(item)
        except Exception:
            logger.exception("%s failed for %s %s", step, type(item).__name__, item.pk)
            failures.append(
                f"{step} failed for {type(item).__name__} {item.pk}\n"
                f"{traceback.format_exc()}"
            )
    if failures:
        raise ItemsFailedError(step, failures)
