from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.classification.models import Party, Tag


@admin.register(Party)
class PartyAdmin(SimpleHistoryAdmin):
    list_display = ("name", "hidden")
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(SimpleHistoryAdmin):
    list_display = ("name", "color", "hidden")
    list_filter = ("color",)
    search_fields = ("name",)
