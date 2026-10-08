"""Username normalisation for django-axes lockouts."""

from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model

if TYPE_CHECKING:
    from django.http import HttpRequest


def lockout_username(
    request: HttpRequest,  # noqa: ARG001
    credentials: dict[str, str] | None,
) -> str:
    """Return the username axes counts failed logins against."""
    # Login matches email case-insensitively, so lockouts must too or each
    # casing would get its own allowance of attempts.
    credentials = credentials or {}
    username = credentials.get(get_user_model().USERNAME_FIELD) or credentials.get(
        "username", ""
    )
    return username.strip().lower()
