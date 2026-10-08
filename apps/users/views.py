from typing import TYPE_CHECKING

from django.shortcuts import render

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


def ratelimited(request: HttpRequest, exception: Exception) -> HttpResponse:  # noqa: ARG001
    return render(request, "429.html", status=429)
