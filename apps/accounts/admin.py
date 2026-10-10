from typing import TYPE_CHECKING

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.accounts.models import Account

if TYPE_CHECKING:
    from django.http import HttpRequest


@admin.register(Account)
class AccountAdmin(SimpleHistoryAdmin):
    list_display = ("name", "kind", "opening_balance", "hidden")
    list_filter = ("kind",)
    search_fields = ("name",)

    def get_readonly_fields(
        self,
        request: HttpRequest,  # noqa: ARG002
        obj: Account | None = None,
    ) -> tuple[str, ...]:
        # An Account never changes kind once created.
        return ("kind",) if obj else ()
