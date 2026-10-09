"""Sign-in and Preferences views."""

from typing import TYPE_CHECKING, Any, cast, override

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.users.client_ip import get_client_ip
from apps.users.forms import PreferencesForm

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

    from apps.users.models import User


class LoginView(auth_views.LoginView):
    """Log in, showing the client's IP."""

    redirect_authenticated_user = True

    @override
    def get_context_data(self, **kwargs: object) -> dict[str, Any]:
        return super().get_context_data(**kwargs) | {
            "client_ip": get_client_ip(self.request)
        }


@login_required
def preferences(request: HttpRequest) -> HttpResponseBase:
    """Edit the user's display preferences."""
    form = PreferencesForm(request.POST or None, instance=cast("User", request.user))
    if form.is_valid():
        form.save()
        messages.success(request, "Preferences saved.")
        return redirect("preferences")
    return render(request, "users/preferences.html", {"form": form})
