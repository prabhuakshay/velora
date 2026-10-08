from typing import TYPE_CHECKING

import pytest
from django.test import RequestFactory

from apps.users.client_ip import get_client_ip

if TYPE_CHECKING:
    from django.http import HttpRequest
    from pytest_django import Settings

PROXY = "10.0.0.1"


def request_from_proxy(forwarded_for: str | None) -> HttpRequest:
    request = RequestFactory().get("/", REMOTE_ADDR=PROXY)
    if forwarded_for is not None:
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded_for
    return request


def test_ignores_forwarded_header_without_trusted_proxies(settings: Settings) -> None:
    settings.TRUSTED_PROXY_COUNT = 0

    assert get_client_ip(request_from_proxy("203.0.113.7")) == PROXY


@pytest.mark.parametrize(
    ("forwarded_for", "proxy_count", "expected"),
    [
        ("203.0.113.7", 1, "203.0.113.7"),
        # A client-forged entry sits left of the one the proxy appended.
        ("6.6.6.6, 203.0.113.7", 1, "203.0.113.7"),
        ("203.0.113.7, 10.0.0.2", 2, "203.0.113.7"),
        ("203.0.113.7", 2, PROXY),
        ("not-an-ip", 1, PROXY),
        (None, 1, PROXY),
    ],
)
def test_reads_client_from_trusted_proxy_hops(
    settings: Settings,
    forwarded_for: str | None,
    proxy_count: int,
    expected: str,
) -> None:
    settings.TRUSTED_PROXY_COUNT = proxy_count

    assert get_client_ip(request_from_proxy(forwarded_for)) == expected
