from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from simple_history.admin import SimpleHistoryAdmin

from apps.users.forms import UserChangeAdminForm, UserCreationAdminForm
from apps.users.models import User


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin, BaseUserAdmin[User]):
    form = UserChangeAdminForm
    add_form = UserCreationAdminForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name",)}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "full_name",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    list_display = ("email", "full_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("email", "full_name")
    ordering = ("email",)
