from typing import TYPE_CHECKING

from apps.users.client_ip import get_client_ip

if TYPE_CHECKING:
    from django.http import HttpRequest


def client_ip(request: HttpRequest) -> dict[str, str]:
    return {"client_ip": get_client_ip(request)}
