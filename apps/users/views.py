"""Sign-in and Preferences views."""

from typing import TYPE_CHECKING, Any, cast, override

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.users.client_ip import get_client_ip
from apps.users.forms import PreferencesForm, PrivacyModeOffForm

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


def _safe_next(request: HttpRequest) -> str:
    next_url = request.POST.get("next") or request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return reverse("index")


@require_POST
@login_required
def privacy_mode_on(request: HttpRequest) -> HttpResponseBase:
    """Turn Privacy Mode on and go back to where the user was."""
    user = cast("User", request.user)
    user.privacy_mode = True
    user.save_without_historical_record(update_fields=["privacy_mode"])
    return redirect(_safe_next(request))


@login_required
def privacy_mode_off(request: HttpRequest) -> HttpResponseBase:
    """Turn Privacy Mode off once the user re-enters their password."""
    user = cast("User", request.user)
    form = PrivacyModeOffForm(request, user, request.POST or None)
    if form.is_valid():
        user.privacy_mode = False
        user.save_without_historical_record(update_fields=["privacy_mode"])
        return redirect(_safe_next(request))
    return render(
        request,
        "users/privacy_mode_off.html",
        {"form": form, "next": _safe_next(request)},
    )
