from typing import TYPE_CHECKING

from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

if TYPE_CHECKING:
    from django.test import Client


def turn_on(client: Client, next_url: str = "/") -> None:
    client.post(reverse("privacy_mode_on"), {"next": next_url})


def privacy_mode_off_url(next_url: str) -> str:
    return redirect_to_login(next_url, reverse("privacy_mode_off"))["Location"]
