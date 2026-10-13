from django.contrib import admin

from apps.investments.models import Instrument


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin[Instrument]):
    list_display = ("name", "isin", "kind", "manual_price")
    list_filter = ("kind", "manual_price")
    search_fields = ("name", "isin")
