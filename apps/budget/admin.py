from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.budget.models import Category, CategoryGroup


@admin.register(CategoryGroup)
class CategoryGroupAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "owner")
    list_filter = ("kind",)
    search_fields = ("name", "owner__email")


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    list_display = ("name", "group", "color")
    list_filter = ("color",)
    search_fields = ("name", "group__name", "group__owner__email")
