"""Background jobs that turn Quick Adds into Drafts (ADR 0005)."""

from procrastinate import JobContext, RetryStrategy
from procrastinate.contrib.django import app

from apps.quick_add import drafting
from apps.quick_add.models import QuickAdd

RETRY = RetryStrategy(
    max_attempts=3,
    exponential_wait=5,
    retry_exceptions={drafting.TransientError},
)


@app.task(name="quick_add.process_quick_add", pass_context=True, retry=RETRY)
def process_quick_add(context: JobContext, quick_add_id: int) -> None:
    """Ask the AI for a Draft of the Quick Add."""
    drafting.draft_quick_add(
        QuickAdd.objects.get(pk=quick_add_id),
        last_attempt=context.job.attempts >= (RETRY.max_attempts or 0),
    )
