from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.accounts.models import Account


@admin.register(Account)
class AccountAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "opening_balance", "hidden")
    list_filter = ("kind",)
    search_fields = ("name",)
