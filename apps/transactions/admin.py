from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.transactions.models import Split, Transaction


class SplitInline(admin.TabularInline[Split, Transaction]):
    model = Split
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(SimpleHistoryAdmin):
    list_display = ("date", "party", "description")
    inlines = (SplitInline,)
