"""Middleware that blocks the Django admin while Privacy Mode is on.

The admin's views are Django's own, so they can't take the
blocked_in_privacy_mode decorator; middleware is the one place to guard them.
"""

from typing import TYPE_CHECKING

from django.conf import settings

from apps.users.privacy_mode import redirect_to_privacy_mode_off

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class PrivacyModeAdminMiddleware:
    """Send admin requests to the Privacy Mode off page while Privacy Mode is on.

    The admin shows real amounts and offers no masking, so it would get
    around Privacy Mode entirely.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.admin_prefix = f"/{settings.ADMIN_URL}"

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Redirect to the Privacy Mode off page, with next pointing back here."""
        if request.path.startswith(self.admin_prefix) and getattr(
            request.user, "privacy_mode", False
        ):
            return redirect_to_privacy_mode_off(request)
        return self.get_response(request)
