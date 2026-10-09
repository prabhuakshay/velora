"""Guard for pages that would show real amounts while Privacy Mode is on."""

from functools import wraps
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from django.shortcuts import redirect
from django.urls import reverse

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from apps.users.models import User

    type View = Callable[..., HttpResponseBase]


def blocked_in_privacy_mode(view: View) -> View:
    """Send the user to the unhide page, coming back here once it's off."""

    @wraps(view)
    def wrapper(
        request: HttpRequest, *args: object, **kwargs: object
    ) -> HttpResponseBase:
        if cast("User", request.user).privacy_mode:
            next_url = quote(request.get_full_path())
            return redirect(f"{reverse('privacy_mode_off')}?next={next_url}")
        return view(request, *args, **kwargs)

    return wrapper
