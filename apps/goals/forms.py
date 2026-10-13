"""Forms for Goals and their Allocations."""

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms

from apps.accounts.models import Account
from apps.core.forms import clean_unique_name
from apps.goals.models import Allocation, Goal
from apps.goals.progress import percent_left
from apps.goals.sources import parse_source, source_choices
from apps.investments.models import Instrument

if TYPE_CHECKING:
    from decimal import Decimal

    from django.db.models import QuerySet


class GoalForm(forms.ModelForm[Goal]):
    """A Goal's target, date, assumptions and linked Schedules."""

    class Meta:
        model = Goal
        fields = (
            "name",
            "target_amount",
            "target_date",
            "inflation",
            "expected_return",
            "schedules",
        )
        labels: ClassVar = {
            "target_amount": "Target (in today's money)",
            "inflation": "Inflation (% a year)",
            "expected_return": "Expected return (% a year)",
            "schedules": "Linked Schedules",
        }
        help_texts: ClassVar = {
            "schedules": "SIPs and other Schedules that keep adding to this Goal.",
        }
        widgets: ClassVar = {
            "target_date": forms.DateInput(attrs={"type": "date"}),
            "schedules": forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.fields["target_amount"].widget.attrs["min"] = "0.01"

    def clean_name(self) -> str:
        """Refuse a name another Goal has, ignoring case."""
        return clean_unique_name(
            self, Goal.objects.all(), "A Goal with this name already exists."
        )


class AllocationForm(forms.ModelForm[Allocation]):
    """A percentage or fixed amount of an Asset Account or Holding for a Goal."""

    source = forms.ChoiceField(label="Allocate from")

    class Meta:
        model = Allocation
        fields = ("percent", "amount")
        labels: ClassVar = {"percent": "Percentage", "amount": "Or a fixed amount"}

    def __init__(self, *args: Any, goal: Goal, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.instance.goal = goal
        source = cast("forms.ChoiceField", self.fields["source"])
        source.choices = [("", "Choose…"), *source_choices()]
        if self.instance.pk:
            self.initial["source"] = self.instance.source_key
        self.fields["percent"].widget.attrs.update(min="0.01", max="100")
        self.fields["amount"].widget.attrs["min"] = "0.01"

    def clean(self) -> dict[str, Any]:
        """Check the share and that the source isn't allocated beyond all of it."""
        data = super().clean() or {}
        percent, amount = data.get("percent"), data.get("amount")
        if (percent is None) == (amount is None):
            message = "Give a percentage or a fixed amount, not both."
            raise forms.ValidationError(message)
        parsed = parse_source(data.get("source", ""))
        if parsed is None:
            return data
        self.instance.account = Account.objects.get(pk=parsed[0])
        self.instance.instrument = (
            None if parsed[1] is None else Instrument.objects.get(pk=parsed[1])
        )
        self._check_source(percent)
        return data

    def _check_source(self, percent: Decimal | None) -> None:
        allocation = self.instance
        others = Allocation.objects.filter(account=allocation.account).exclude(
            pk=allocation.pk
        )
        same = others.filter(instrument=allocation.instrument)
        if same.filter(goal=allocation.goal).exists():
            message = "This Goal already has an Allocation of it; edit that one."
            raise forms.ValidationError(message)
        _refuse_whole_and_holdings(allocation, others)
        left = percent_left(a.share for a in same)
        if percent is not None and percent > left:
            free = f"{left.normalize():f}%"
            message = f"Only {free} of {allocation.source_label} is unallocated."
            raise forms.ValidationError(message)


def _refuse_whole_and_holdings(
    allocation: Allocation, others: QuerySet[Allocation]
) -> None:
    whole = allocation.instrument is None
    if others.filter(instrument__isnull=not whole).exists():
        message = (
            f"{allocation.account.name} is allocated through its Holdings; "
            "allocate those, not the whole account."
            if whole
            else f"{allocation.account.name} is allocated as a whole; "
            "allocate that, not one of its Holdings."
        )
        raise forms.ValidationError(message)
