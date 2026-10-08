from typing import TYPE_CHECKING, Any, NamedTuple

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.template.loader import render_to_string

if TYPE_CHECKING:
    from django.http import HttpRequest


class Preview(NamedTuple):
    template: str
    status: int
    # Django renders these pages without a request (so no context processors);
    # a context here mimics that instead of rendering with the request.
    context: dict[str, Any] | None = None


PREVIEWS = {
    "400": Preview("400.html", 400),
    "403": Preview("403.html", 403),
    "403-csrf": Preview(
        "403_csrf.html",
        403,
        {"reason": "CSRF token missing.", "no_cookie": False, "DEBUG": True},
    ),
    "404": Preview("404.html", 404),
    "429": Preview("429.html", 429),
    "429-locked": Preview("registration/locked_out.html", 429),
    "500": Preview("500.html", 500, {}),
}


def _require_access(request: HttpRequest) -> None:
    # With DEBUG on, Django shows its technical pages instead of these templates.
    if not (settings.DEBUG or request.user.is_superuser):
        raise Http404


def index(request: HttpRequest) -> HttpResponse:
    _require_access(request)
    return render(request, "errors/previews.html", {"previews": PREVIEWS})


def preview(request: HttpRequest, name: str) -> HttpResponse:
    _require_access(request)
    page = PREVIEWS.get(name)
    if page is None:
        raise Http404
    if page.context is None:
        return render(request, page.template, status=page.status)
    return HttpResponse(
        render_to_string(page.template, page.context), status=page.status
    )
