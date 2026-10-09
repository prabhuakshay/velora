"""Middleware that enforces Privacy Mode across the site."""

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class PrivacyModeAdminMiddleware:
    """Send admin requests to the unhide page while Privacy Mode is on.

    The admin shows real amounts and offers no masking, so it would get
    around Privacy Mode entirely.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.admin_prefix = f"/{settings.ADMIN_URL}"

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Redirect to the unhide page, with next pointing back here."""
        if request.path.startswith(self.admin_prefix) and getattr(
            request.user, "privacy_mode", False
        ):
            return redirect_to_login(
                request.get_full_path(), reverse("privacy_mode_off")
            )
        return self.get_response(request)
