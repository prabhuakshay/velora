"""Account views."""

from typing import Any, override

from django.contrib.auth import views as auth_views

from apps.users.client_ip import get_client_ip


class LoginView(auth_views.LoginView):
    """Log in, showing the client's IP."""

    redirect_authenticated_user = True

    @override
    def get_context_data(self, **kwargs: object) -> dict[str, Any]:
        return super().get_context_data(**kwargs) | {
            "client_ip": get_client_ip(self.request)
        }
