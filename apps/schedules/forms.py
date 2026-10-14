"""Forms for a Schedule's rule and the Splits it proposes."""

from typing import Any, ClassVar

from croniter import croniter
from django import forms
from django.utils import timezone

from apps.investments.instrument_field import InstrumentField
from apps.investments.models import Instrument
from apps.schedules.models import Schedule, ScheduleSplit
from apps.schedules.repeat import cron_dates
from apps.transactions.forms import offer_accounts, offer_parties
from apps.transactions.split_rules import accounts_error, shared_account_error

# Days ahead to remind when the user leaves it blank, by repeat unit.
REMINDER_DAYS: dict[str, int] = {
    Schedule.Unit.DAY: 0,
    Schedule.Unit.WEEK: 1,
    Schedule.Unit.MONTH: 3,
    Schedule.Unit.YEAR: 14,
}
SIP_INSTRUMENT = InstrumentField("sip_", creates_from_isin=False)


class ScheduleForm(forms.ModelForm[Schedule]):
    """The Schedule's template fields and its repeat rule."""

    is_sip = forms.BooleanField(
        label="SIP",
        required=False,
        help_text="It buys one Instrument in a Direct Investment Account.",
    )

    class Meta:
        model = Schedule
        fields = (
            "party",
            "description",
            "start_date",
            "every",
            "unit",
            "cron",
            "ends_on",
            "ends_after",
            "auto_post",
            "grace_days",
            "reminder_days",
            "is_subscription",
            "trial_ends_on",
            "plan",
            "how_to_cancel",
            "sip_account",
        )
        labels: ClassVar = {
            "start_date": "First due date",
            "every": "Repeat every",
            "unit": "",
            "cron": "Or on a cron expression",
            "ends_on": "Last due date",
            "ends_after": "Number of Occurrences",
            "reminder_days": "Remind days before",
            "auto_post": "Auto-post",
            "is_subscription": "Subscription",
            "trial_ends_on": "Trial ends on",
            "sip_account": "Investment Account",
        }
        help_texts: ClassVar = {
            "cron": (
                "Replaces the interval, such as 0 0 * * 5#2 for the 2nd Friday. "
                "Only the day fields count."
            ),
            "ends_on": "Leave blank to repeat until you end it.",
            "ends_after": "Leave blank for no limit.",
            "auto_post": (
                "Record the Transaction on each due date instead of proposing a "
                "Draft. Needs an amount on every Split."
            ),
            "grace_days": "Days after the due date before it counts as Missed.",
            "reminder_days": "Leave blank for "
            + ", ".join(
                f"{days} if every {unit}" for unit, days in REMINDER_DAYS.items()
            )
            + "; a cron expression is reminded as every month.",
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
        self.fields |= SIP_INSTRUMENT.fields()
        self.sip_instrument_parts = SIP_INSTRUMENT.parts(self)
        offer_parties(self)
        self.fields["reminder_days"].required = False
        if not self.instance.pk:
            self.initial["reminder_days"] = None
        if instrument := self.instance.sip_instrument:
            self.initial["is_sip"] = True
            self.initial.update(SIP_INSTRUMENT.initial(instrument))

    def clean_cron(self) -> str:
        """Refuse an expression croniter can't read or that never falls due."""
        cron = " ".join(self.cleaned_data["cron"].split())
        if cron and (
            not croniter.is_valid(cron)
            or next(cron_dates(cron, timezone.localdate()), None) is None
        ):
            msg = "Not a valid cron expression."
            raise forms.ValidationError(msg)
        return cron

    def clean(self) -> dict[str, Any]:
        """Keep one repeat rule, default blank reminder days, check the dates."""
        super().clean()
        cleaned = self.cleaned_data
        if cleaned.get("cron"):
            cleaned |= {"every": None, "unit": ""}
        elif "cron" in cleaned and not (cleaned.get("every") and cleaned.get("unit")):
            self.add_error(None, "Repeat every so often or on a cron expression.")
        if cleaned.get("reminder_days") is None:
            # A cron expression has no unit; remind as for a monthly one.
            cleaned["reminder_days"] = REMINDER_DAYS.get(
                cleaned.get("unit", ""), REMINDER_DAYS[Schedule.Unit.MONTH]
            )
        start, end = cleaned.get("start_date"), cleaned.get("ends_on")
        if start and end and end < start:
            self.add_error("ends_on", "The last due date cannot be before the first.")
        self._clean_sip()
        return cleaned

    def _clean_sip(self) -> None:
        """Require a SIP's Investment Account and its Instrument."""
        cleaned = self.cleaned_data
        if not cleaned.get("is_sip"):
            cleaned["sip_account"] = None
            self.instance.sip_instrument = None
            return
        if "sip_account" in cleaned and cleaned["sip_account"] is None:
            self.add_error("sip_account", "Pick the Investment Account it buys in.")
        self.instance.sip_instrument = SIP_INSTRUMENT.resolve(
            self, default_kind=Instrument.Kind.MUTUAL_FUND
        )

    def save(self, commit: bool = True) -> Schedule:  # noqa: FBT001, FBT002
        """Save a SIP's Instrument first when it was added with it."""
        if commit:
            InstrumentField.save_if_new(self.instance.sip_instrument)
        return super().save(commit=commit)


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
        offer_accounts(self)
        self.fields["amount"].widget.attrs["placeholder"] = "Open amount"

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


type SplitFormSet = forms.BaseInlineFormSet[ScheduleSplit, Schedule, ScheduleSplitForm]


def _kept(formset: SplitFormSet) -> list[dict[str, Any]]:
    """The cleaned data of the valid formset's kept Splits."""
    return [
        form.cleaned_data
        for form in formset.forms
        if form.cleaned_data and not form.cleaned_data.get("DELETE")
    ]


def splits_fit(form: ScheduleForm, formset: SplitFormSet) -> bool:
    """Whether the valid formset's Splits suit the valid Schedule form.

    Auto-post needs every amount, and a SIP pays its Investment Account from
    its Pays from Account in one Split; otherwise the form gets the error.
    """
    kept = _kept(formset)
    if form.cleaned_data["auto_post"] and any(
        split["amount"] is None for split in kept
    ):
        form.add_error("auto_post", "Auto-post needs an amount on every Split.")
        return False
    account = form.cleaned_data.get("sip_account")
    if account is not None and [
        (split["from_account"], split["to_account"]) for split in kept
    ] != [(account.invests_from, account)]:
        form.add_error(
            None, f"A SIP has one Split, from {account.invests_from} into {account}."
        )
        return False
    return True
