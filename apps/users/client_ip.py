"""Client IP resolution behind trusted reverse proxies."""

import ipaddress
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from django.http import HttpRequest


def get_client_ip(request: HttpRequest) -> str:
    """Return the client's IP, trusting only the configured proxies."""
    remote_addr = str(request.META.get("REMOTE_ADDR", ""))
    proxy_count: int = settings.TRUSTED_PROXY_COUNT
    if not proxy_count:
        return remote_addr

    # Each trusted proxy appends the address it received from, so the client is
    # proxy_count entries from the right. Anything further left is
    # client-supplied and can be forged.
    forwarded = [
        ip.strip() for ip in str(request.headers.get("x-forwarded-for", "")).split(",")
    ]
    if len(forwarded) < proxy_count:
        return remote_addr
    candidate = forwarded[-proxy_count]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return remote_addr
    return candidate
