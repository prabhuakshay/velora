"""Forms for the email-based user model."""

from typing import TYPE_CHECKING, Any, cast, override
from urllib.parse import urlsplit

from axes.utils import reset
from django import forms
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.forms import (
    AdminUserCreationForm,
    PasswordChangeForm,
    PasswordResetForm,
    UserChangeForm,
)
from django.views.decorators.debug import sensitive_variables

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


def password_is_correct(request: HttpRequest, password: str) -> bool:
    """Check the signed-in user's password the way login does."""
    email = cast("User", request.user).email
    # authenticate, not check_password, so axes counts a wrong password
    # and refuses a locked-out user exactly as it does at login.
    if not authenticate(request, username=email, password=password):
        return False
    # authenticate doesn't log in, so axes never sees the success that
    # would clear this user's failures (AXES_RESET_ON_SUCCESS) at login.
    reset(ip=get_client_ip(request), username=email)
    return True


class PrivacyModeOffForm(forms.Form):
    """The user's password, needed to turn Privacy Mode off."""

    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "autofocus": True}
        ),
    )

    def __init__(self, request: HttpRequest, data: object = None) -> None:
        super().__init__(data)  # type: ignore[arg-type]
        self.request = request

    @override
    def clean(self) -> dict[str, object]:
        """Reject a wrong password."""
        cleaned = super().clean() or {}
        if "password" in cleaned and not password_is_correct(
            self.request, cleaned["password"]
        ):
            msg = "Wrong password."
            raise forms.ValidationError(msg)
        return cleaned


class AxesPasswordChangeForm(PasswordChangeForm):
    """Change password, counting wrong old passwords toward the axes lockout."""

    def __init__(self, *args: Any, request: HttpRequest, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.request = request

    @override
    @sensitive_variables("old_password")
    def clean_old_password(self) -> str:
        old_password = str(self.cleaned_data["old_password"])
        if not password_is_correct(self.request, old_password):
            raise forms.ValidationError(
                self.error_messages["password_incorrect"], code="password_incorrect"
            )
        return old_password


class SiteURLPasswordResetForm(PasswordResetForm):
    """Build reset links from SITE_URL, so a spoofed Host can't redirect them."""

    @override
    def save(self, *args: Any, **kwargs: Any) -> None:
        site = urlsplit(settings.SITE_URL)
        kwargs["domain_override"] = site.netloc
        kwargs["use_https"] = site.scheme == "https"
        super().save(*args, **kwargs)
