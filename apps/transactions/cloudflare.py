"""The Cloudflare analytics client: the only code that talks HTTP to Cloudflare.

Queries go to the GraphQL Analytics API for the Attachment R2 bucket. Tests
replace the query functions (`daily_storage`) with fakes, so nothing else here
needs faking.
"""

import json
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from django.conf import settings

URL = "https://api.cloudflare.com/client/v4/graphql"
TIMEOUT_SECONDS = 10
# R2 analytics are kept for at least 31 days, and 31 days is also the longest
# range one query may cover.
RETENTION = timedelta(days=31)

DAILY_STORAGE_QUERY = """
query ($accountTag: string!, $bucketName: string, $start: Time, $end: Time) {
  viewer {
    accounts(filter: { accountTag: $accountTag }) {
      r2StorageAdaptiveGroups(
        limit: 10000
        filter: { bucketName: $bucketName, datetime_geq: $start, datetime_leq: $end }
        orderBy: [datetime_ASC]
      ) {
        max { payloadSize metadataSize }
        dimensions { datetime }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class DailyStorage:
    """The bucket's stored size in bytes on one day (UTC)."""

    day: date
    size: int


def is_configured() -> bool:
    """Whether analytics credentials are set; the section is hidden without them."""
    return bool(settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_API_TOKEN)


def bucket_name() -> str:
    """The Attachment bucket, as the storage settings name it."""
    storage = cast("dict[str, dict[str, str]]", settings.STORAGES["default"])
    return storage["OPTIONS"]["bucket_name"]


def query(text: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Run a GraphQL query and return the configured account's node.

    Raises urllib.error.URLError (HTTPError for non-2xx) on network failures,
    and ValueError when the response carries errors or isn't the expected JSON.
    """
    request = urllib.request.Request(
        URL,
        data=json.dumps(
            {
                "query": text,
                "variables": {
                    "accountTag": settings.CLOUDFLARE_ACCOUNT_ID,
                    **variables,
                },
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        data = json.load(response)
    # GraphQL reports errors with a 200 status.
    if not isinstance(data, dict) or data.get("errors"):
        msg = f"Cloudflare analytics query failed: {data!r:.500}"
        raise ValueError(msg)
    try:
        account: dict[str, Any] = data["data"]["viewer"]["accounts"][0]
    except KeyError, IndexError, TypeError:
        msg = "Cloudflare's response has no account data."
        raise ValueError(msg) from None
    return account


def daily_storage() -> list[DailyStorage]:
    """The bucket's stored size per day, oldest first, over the retained days."""
    end = datetime.now(UTC)
    account = query(
        DAILY_STORAGE_QUERY,
        {
            "bucketName": bucket_name(),
            "start": (end - RETENTION).isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
        },
    )
    # The dataset is grouped by timestamp, not by day, so keep each day's peak.
    sizes: dict[date, int] = {}
    for group in account["r2StorageAdaptiveGroups"]:
        day = datetime.fromisoformat(group["dimensions"]["datetime"]).date()
        size = group["max"]["payloadSize"] + group["max"]["metadataSize"]
        sizes[day] = max(sizes.get(day, 0), size)
    return [DailyStorage(day=day, size=size) for day, size in sorted(sizes.items())]
