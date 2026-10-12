"""Deleting Attachments' stored files in the background (ADR 0004, 0005)."""

from contextlib import suppress

from django.core.files.storage import default_storage
from procrastinate import RetryStrategy
from procrastinate.contrib.django import app

# Waits grow from 3 seconds to about 16 hours, riding out an R2 outage of a day.
RETRY = RetryStrategy(max_attempts=10, exponential_wait=3)


@app.task(name="transactions.delete_stored_file", retry=RETRY)
def delete_stored_file(name: str) -> None:
    """Delete the stored file; one already gone counts as deleted."""
    with suppress(FileNotFoundError):
        default_storage.delete(name)
