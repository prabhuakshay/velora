"""The bucket client: the only code that lists the Attachment R2 bucket.

Tests replace `list_objects` with a fake, so nothing else here needs faking.
"""

from typing import cast

import boto3
from botocore.config import Config
from django.conf import settings


def list_objects() -> list[tuple[str, int]]:
    """Every object in the whole bucket as (key, size in bytes)."""
    default = cast("dict[str, dict[str, str]]", settings.STORAGES["default"])
    options = default["OPTIONS"]
    client = boto3.client(
        "s3",
        endpoint_url=options["endpoint_url"],
        aws_access_key_id=options["access_key"],
        aws_secret_access_key=options["secret_key"],
        region_name="auto",
        config=Config(connect_timeout=5, read_timeout=10),
    )
    pages = client.get_paginator("list_objects_v2").paginate(
        Bucket=options["bucket_name"]
    )
    # An empty bucket's page has no "Contents".
    return [
        (obj["Key"], obj["Size"]) for page in pages for obj in page.get("Contents", [])
    ]
