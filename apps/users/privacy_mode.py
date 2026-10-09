"""Guards for pages that would show real amounts while Privacy Mode is on."""

from functools import wraps
from typing import TYPE_CHECKING, cast

from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponseRedirect
    from django.http.response import HttpResponseBase

    from apps.users.models import User

    type View = Callable[..., HttpResponseBase]


def redirect_to_privacy_mode_off(request: HttpRequest) -> HttpResponseRedirect:
    """Send the user to the Privacy Mode off page, with next pointing back here."""
    return redirect_to_login(request.get_full_path(), reverse("privacy_mode_off"))


def blocked_in_privacy_mode(view: View) -> View:
    """Send the user to the Privacy Mode off page, coming back once it's off."""

    @wraps(view)
    def wrapper(
        request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        if cast("User", request.user).privacy_mode:
            return redirect_to_privacy_mode_off(request)
        return view(request, *args, **kwargs)

    return wrapper
