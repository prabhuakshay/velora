from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from apps.users.models import User


class UserCreationAdminForm(AdminUserCreationForm[User]):
    class Meta:
        model = User
        fields = ("email", "full_name")


class UserChangeAdminForm(UserChangeForm[User]):
    class Meta:
        model = User
        fields = "__all__"
