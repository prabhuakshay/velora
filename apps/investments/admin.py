from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.investments.models import Instrument, InvestmentEvent


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin[Instrument]):
    list_display = ("name", "isin", "kind", "price_source")
    list_filter = ("kind",)
    search_fields = ("name", "isin")


@admin.register(InvestmentEvent)
class InvestmentEventAdmin(SimpleHistoryAdmin):
    list_display = ("date", "kind", "instrument", "account", "units", "amount")
    list_filter = ("kind", "account")
    search_fields = ("instrument__name", "instrument__isin")
