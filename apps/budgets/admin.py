from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.budgets.models import Budget


@admin.register(Budget)
class BudgetAdmin(SimpleHistoryAdmin):
    list_display = ("account", "month", "amount")
    list_filter = ("month",)
