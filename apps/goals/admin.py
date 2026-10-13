from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.goals.models import Allocation, Goal


@admin.register(Goal)
class GoalAdmin(SimpleHistoryAdmin):
    list_display = ("name", "target_amount", "target_date")
    search_fields = ("name",)


@admin.register(Allocation)
class AllocationAdmin(SimpleHistoryAdmin):
    list_display = ("goal", "account", "instrument", "percent", "amount")
    list_filter = ("goal",)
