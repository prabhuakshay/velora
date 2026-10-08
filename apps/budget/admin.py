from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.budget.models import CategoryGroup


@admin.register(CategoryGroup)
class CategoryGroupAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "owner")
    list_filter = ("kind",)
    search_fields = ("name", "owner__email")
