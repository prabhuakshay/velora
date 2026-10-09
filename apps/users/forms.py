"""Forms for the email-based user model."""

from typing import TYPE_CHECKING, override

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

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

    def __init__(self, request: HttpRequest, user: User, data: object = None) -> None:
        super().__init__(data)  # type: ignore[arg-type]
        self.request = request
        self.user = user

    @override
    def clean(self) -> dict[str, object]:
        """Reject a wrong password."""
        cleaned = super().clean() or {}
        # authenticate, not check_password, so axes counts a wrong password
        # and refuses a locked-out user exactly as it does at login.
        if "password" in cleaned and not authenticate(
            self.request, username=self.user.email, password=cleaned["password"]
        ):
            msg = "Wrong password."
            raise forms.ValidationError(msg)
        return cleaned
