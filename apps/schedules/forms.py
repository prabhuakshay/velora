"""Forms for a Schedule's rule and the Splits it proposes."""

from typing import Any, ClassVar, cast

from django import forms
from django.db.models.functions import Lower

from apps.accounts.models import Account
from apps.classification.models import Party
from apps.schedules.models import Schedule, ScheduleSplit
from apps.transactions.forms import grouped_by_kind, visible_or_current
from apps.transactions.split_rules import accounts_error, shared_account_error

# Days ahead to remind when the user leaves it blank, by repeat unit.
REMINDER_DAYS = {
    Schedule.Unit.DAY: 0,
    Schedule.Unit.WEEK: 1,
    Schedule.Unit.MONTH: 3,
    Schedule.Unit.YEAR: 14,
}


class ScheduleForm(forms.ModelForm[Schedule]):
    """The Schedule's template fields and its repeat rule."""

    class Meta:
        model = Schedule
        fields = (
            "party",
            "description",
            "start_date",
            "every",
            "unit",
            "ends_on",
            "grace_days",
            "reminder_days",
            "is_subscription",
            "trial_ends_on",
            "plan",
            "how_to_cancel",
        )
        labels: ClassVar = {
            "start_date": "First due date",
            "every": "Repeat every",
            "unit": "",
            "ends_on": "Last due date",
            "reminder_days": "Remind days before",
            "is_subscription": "Subscription",
            "trial_ends_on": "Trial ends on",
        }
        help_texts: ClassVar = {
            "ends_on": "Leave blank to repeat until you end it.",
            "grace_days": "Days after the due date before it counts as Missed.",
            "reminder_days": "Leave blank for 3 if monthly, 14 if yearly.",
            "is_subscription": "It pays for an ongoing service.",
        }
        widgets: ClassVar = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
            "trial_ends_on": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
            "how_to_cancel": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        party = cast("forms.ModelChoiceField[Party]", self.fields["party"])
        party.queryset = visible_or_current(
            Party.objects.order_by(Lower("name")), self.instance.party_id
        )
        self.fields["reminder_days"].required = False
        if not self.instance.pk:
            self.initial["reminder_days"] = None

    def clean(self) -> dict[str, Any]:
        """Default blank reminder days by unit; refuse a last due date first."""
        super().clean()
        cleaned = self.cleaned_data
        if cleaned.get("reminder_days") is None and (unit := cleaned.get("unit")):
            cleaned["reminder_days"] = REMINDER_DAYS[unit]
        start, end = cleaned.get("start_date"), cleaned.get("ends_on")
        if start and end and end < start:
            self.add_error("ends_on", "The last due date cannot be before the first.")
        return cleaned


class ScheduleSplitForm(forms.ModelForm[ScheduleSplit]):
    """One Split of the template; its amount may be left open."""

    class Meta:
        model = ScheduleSplit
        fields = ("from_account", "to_account", "amount")
        labels: ClassVar = {"from_account": "From", "to_account": "To"}
        help_texts: ClassVar = {"amount": "Leave blank when it changes every time."}
        error_messages: ClassVar = {
            name: {"invalid_choice": "That Account is inactive or no longer exists."}
            for name in ("from_account", "to_account")
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        accounts = visible_or_current(
            Account.objects.all(),
            self.instance.from_account_id,
            self.instance.to_account_id,
        )
        for name in ("from_account", "to_account"):
            field = cast("forms.ModelChoiceField[Account]", self.fields[name])
            field.queryset = accounts
            field.choices = grouped_by_kind(accounts)

    def clean(self) -> dict[str, Any]:
        """Apply the shared Split rules to the two Accounts."""
        super().clean()
        cleaned = self.cleaned_data
        source, destination = cleaned.get("from_account"), cleaned.get("to_account")
        if source and destination and (error := accounts_error(source, destination)):
            raise forms.ValidationError(error)
        return cleaned


class BaseScheduleSplitFormSet(
    forms.BaseInlineFormSet[ScheduleSplit, Schedule, ScheduleSplitForm]
):
    """The Split rows of one Schedule, at least one of them kept."""

    default_error_messages: ClassVar = {
        **forms.BaseInlineFormSet.default_error_messages,
        "too_few_forms": "Add at least one Split.",
    }

    def clean(self) -> None:
        """Require the kept Splits to share a From or a To Account."""
        super().clean()
        kept = [
            form.cleaned_data
            for form in self.forms
            if form.is_valid()
            and form.cleaned_data
            and not form.cleaned_data.get("DELETE")
        ]
        if error := shared_account_error(
            (data.get("from_account"), data.get("to_account")) for data in kept
        ):
            raise forms.ValidationError(error)


ScheduleSplitFormSet = forms.inlineformset_factory(
    Schedule,
    ScheduleSplit,
    form=ScheduleSplitForm,
    formset=BaseScheduleSplitFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)
