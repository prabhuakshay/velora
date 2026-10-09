from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.budget.models import Category, ExpenseAccount


@admin.register(Category)
class CategoryAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "color")
    list_filter = ("kind", "color")
    search_fields = ("name",)


@admin.register(ExpenseAccount)
class ExpenseAccountAdmin(SimpleHistoryAdmin):
    list_display = ("name", "hidden")
    search_fields = ("name",)
