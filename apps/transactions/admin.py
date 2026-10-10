from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.transactions.forms import BaseSplitFormSet, SplitForm
from apps.transactions.models import Split, Transaction


class AdminSplitFormSet(BaseSplitFormSet):
    """The Split rules the app applies, Opening Balance check included."""

    def clean(self) -> None:
        super().clean()
        # The admin sets the Transaction's date on the instance before this runs.
        if self.instance.date:
            self.check_opening_balances(self.instance.date)


class SplitInline(admin.TabularInline[Split, Transaction]):
    model = Split
    form = SplitForm
    formset = AdminSplitFormSet  # type: ignore[assignment]
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(SimpleHistoryAdmin):
    list_display = ("date", "party", "description")
    inlines = (SplitInline,)
