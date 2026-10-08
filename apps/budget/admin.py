from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.budget.models import Category, Party


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "owner", "color")
    list_filter = ("kind", "color")
    search_fields = ("name", "owner__email")


@admin.register(Party)
class PartyAdmin(SimpleHistoryAdmin):
    list_display = ("name", "owner", "hidden")
    search_fields = ("name", "owner__email")
