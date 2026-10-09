"""Project-wide middleware that does not belong to any one app."""

from typing import TYPE_CHECKING

from django.db import connection
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers

from apps.transactions.attachment_rules import MAX_REQUEST_BYTES, MAX_TOTAL_MB

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest


class NoStoreMiddleware:
    """Keep pages out of browser and back-forward caches.

    Without this, the back button can redisplay a signed-in page after logout.
    A future PWA service worker must also skip caching these responses.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Add no-cache headers unless the view already set Cache-Control."""
        response = self.get_response(request)
        if not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        return response


class HealthCheckMiddleware:
    """Answer container health probes at /healthz/.

    Runs first in MIDDLEWARE so probes from 127.0.0.1 skip ALLOWED_HOSTS
    validation and the HTTPS redirect, which would otherwise fail them.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Return "ok" once the database is reachable; pass other paths on."""
        if request.path == "/healthz/":
            connection.ensure_connection()
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


class RequestSizeMiddleware:
    """Refuse a request declaring a body too large for any form to accept.

    Django spools large uploads to /tmp, which is a small tmpfs in production,
    so the refusal must come before anything reads the body.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Return 413 when Content-Length is over the limit; pass others on."""
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > MAX_REQUEST_BYTES:
            return render(
                request, "413.html", {"max_total_mb": MAX_TOTAL_MB}, status=413
            )
        return self.get_response(request)
