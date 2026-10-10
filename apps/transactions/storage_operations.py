"""This month's R2 operations, split into Cloudflare's billing classes."""

from dataclasses import dataclass

# Cloudflare's published classification (R2 pricing page). Actions on neither
# list, such as DeleteObject, are free or unknown and count towards no class.
CLASS_A = frozenset(
    {
        "ListBuckets",
        "PutBucket",
        "ListObjects",
        "PutObject",
        "CopyObject",
        "CompleteMultipartUpload",
        "CreateMultipartUpload",
        "LifecycleStorageTierTransition",
        "ListMultipartUploads",
        "UploadPart",
        "UploadPartCopy",
        "ListParts",
        "PutBucketEncryption",
        "PutBucketCors",
        "PutBucketLifecycleConfiguration",
    }
)
CLASS_B = frozenset(
    {
        "HeadBucket",
        "HeadObject",
        "GetObject",
        "UsageSummary",
        "GetBucketEncryption",
        "GetBucketLocation",
        "GetBucketCors",
        "GetBucketLifecycleConfiguration",
    }
)


@dataclass(frozen=True)
class Operations:
    """Class A and Class B totals plus every action's count, busiest first."""

    class_a: int
    class_b: int
    actions: list[tuple[str, int]]


def count_operations(counts: dict[str, int]) -> Operations:
    """Total the per-action counts into their classes."""
    return Operations(
        class_a=sum(n for action, n in counts.items() if action in CLASS_A),
        class_b=sum(n for action, n in counts.items() if action in CLASS_B),
        actions=sorted(counts.items(), key=lambda item: (-item[1], item[0])),
    )
