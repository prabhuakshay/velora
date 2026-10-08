"""Per-IP rate limiting for POST views."""

from functools import wraps
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

from apps.users.client_ip import get_client_ip

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    type View = Callable[..., HttpResponseBase]

UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_rate(rate: str) -> tuple[int, int]:
    """Parse "<count>/<s|m|h|d>" into a request count and window in seconds."""
    count, _, unit = rate.partition("/")
    if not count.isdigit() or unit not in UNIT_SECONDS:
        msg = f"Invalid rate {rate!r}, expected '<count>/<s|m|h|d>'"
        raise ImproperlyConfigured(msg)
    return int(count), UNIT_SECONDS[unit]


def throttle(setting: str) -> Callable[[View], View]:
    """Limit POSTs per client IP to the "<count>/<s|m|h|d>" rate in `setting`."""

    def decorator(view: View) -> View:
        @wraps(view)
        def wrapper(
            request: HttpRequest, *args: object, **kwargs: object
        ) -> HttpResponse | HttpResponseBase:
            if request.method == "POST":
                limit, window = parse_rate(str(getattr(settings, setting)))
                key = f"throttle:{setting}:{get_client_ip(request)}"
                # add creates the counter with its expiry only if absent, so the
                # window starts at the first request and incr never extends it.
                cache.add(key, 0, window)
                try:
                    count = cache.incr(key)
                except ValueError:
                    # The key expired between add and incr; start a new window.
                    cache.set(key, 1, window)
                    count = 1
                if count > limit:
                    return HttpResponse("Too many requests.", status=429)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
