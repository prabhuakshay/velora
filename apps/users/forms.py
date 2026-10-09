"""Admin forms for the email-based user model."""

from django import forms
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from apps.users.models import User


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
