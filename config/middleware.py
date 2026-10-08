from typing import TYPE_CHECKING

from django.utils.cache import add_never_cache_headers

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class NoStoreMiddleware:
    """Keep pages out of browser and back-forward caches.

    Without this, the back button can redisplay a signed-in page after logout.
    A future PWA service worker must also skip caching these responses.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        return response
