"""Template context processors."""

from typing import TYPE_CHECKING

from apps.users.client_ip import get_client_ip

if TYPE_CHECKING:
    from django.http import HttpRequest


def client_ip(request: HttpRequest) -> dict[str, str]:
    """Expose the client's IP to templates."""
    return {"client_ip": get_client_ip(request)}
