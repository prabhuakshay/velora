"""The bucket client: the only code that lists the Attachment R2 bucket.

It reuses the Attachment storage backend's configured bucket. Tests replace
`bucket_name` and `list_objects` with fakes, so nothing else here needs faking.
"""

from typing import Any, cast

from django.core.files.storage import default_storage


def _storage() -> Any:  # noqa: ANN401
    # R2Storage, whose boto3 attributes django-storages leaves untyped.
    return cast("Any", default_storage)


def bucket_name() -> str:
    """The Attachment bucket's name."""
    return str(_storage().bucket_name)


def list_objects() -> dict[str, int]:
    """Every object in the whole bucket: size in bytes by key."""
    # Paged ListObjectsV2 summaries carry sizes, so no HEAD per object.
    return {obj.key: obj.size for obj in _storage().bucket.objects.all()}
