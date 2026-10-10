"""What the R2 bucket actually holds, reconciled with Velora's Attachments."""

from dataclasses import dataclass

from apps.transactions import r2_bucket
from apps.transactions.models import Attachment


@dataclass(frozen=True)
class BucketStats:
    """The bucket section's figures; sizes are in bytes."""

    objects: int
    total_size: int
    # Objects with no Attachment, anywhere in the bucket.
    untracked: int
    untracked_size: int
    # Attachments whose object isn't in the bucket.
    missing: int


def bucket_stats() -> BucketStats:
    """List the whole bucket and compare its keys with Attachment file names."""
    objects = r2_bucket.list_objects()
    stored = set(Attachment.objects.values_list("file", flat=True))
    untracked = [size for key, size in objects.items() if key not in stored]
    return BucketStats(
        objects=len(objects),
        total_size=sum(objects.values()),
        untracked=len(untracked),
        untracked_size=sum(untracked),
        missing=len(stored - objects.keys()),
    )
