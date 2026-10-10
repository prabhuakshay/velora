"""Forms for the email-based user model."""

from typing import TYPE_CHECKING, Any, cast, override
from urllib.parse import urlsplit

from axes.utils import reset
from django import forms
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AdminUserCreationForm,
    PasswordResetForm,
    UserChangeForm,
)

from apps.users.client_ip import get_client_ip
from apps.users.models import User

if TYPE_CHECKING:
    from django.http import HttpRequest


class UserCreationAdminForm(AdminUserCreationForm[User]):
    """Admin form for adding a user by email."""

    class Meta:
        model = User
        fields = ("email", "full_name")


class UserChangeAdminForm(UserChangeForm[User]):
    """Admin form for editing a user."""

    class Meta:
        model = User
        fields = "__all__"


class PreferencesForm(forms.ModelForm[User]):
    """The user's display preferences."""

    class Meta:
        model = User
        fields = ("number_format",)


class PrivacyModeOffForm(forms.Form):
    """The user's password, needed to turn Privacy Mode off."""

    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request: HttpRequest, data: object = None) -> None:
        super().__init__(data)  # type: ignore[arg-type]
        self.request = request

    @override
    def clean(self) -> dict[str, object]:
        """Reject a wrong password."""
        cleaned = super().clean() or {}
        # authenticate, not check_password, so axes counts a wrong password
        # and refuses a locked-out user exactly as it does at login.
        if "password" not in cleaned:
            return cleaned
        email = cast("User", self.request.user).email
        if not authenticate(self.request, username=email, password=cleaned["password"]):
            msg = "Wrong password."
            raise forms.ValidationError(msg)
        # authenticate doesn't log in, so axes never sees the success that
        # would clear this user's failures (AXES_RESET_ON_SUCCESS) at login.
        reset(ip=get_client_ip(self.request), username=email)
        return cleaned


class SiteURLPasswordResetForm(PasswordResetForm):
    """Build reset links from SITE_URL, so a spoofed Host can't redirect them."""

    @override
    def save(self, *args: Any, **kwargs: Any) -> None:
        site = urlsplit(settings.SITE_URL)
        kwargs["domain_override"] = site.netloc
        kwargs["use_https"] = site.scheme == "https"
        super().save(*args, **kwargs)
