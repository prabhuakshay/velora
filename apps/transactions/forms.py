"""Forms for recording a Transaction and its Splits."""

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms
from django.db.models import Q, QuerySet
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.models import BALANCE_KINDS, Account
from apps.classification.models import Party, Tag
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from collections.abc import Iterable

Kind = Account.Kind


def direction_error(source: Account, destination: Account) -> str | None:
    """Why a Split may not move money between these Accounts, if it may not."""
    if destination.kind == Kind.INCOME:
        return "An Income Account can only be a source."
    if source.kind == Kind.INCOME and destination.kind == Kind.EXPENSE:
        return "A Split cannot go from an Income Account to an Expense Account."
    if source.kind == Kind.EXPENSE and destination.kind not in BALANCE_KINDS:
        return (
            "An Expense Account can only be a source in a Refund to an Asset "
            "or Liability Account."
        )
    return None


def visible_or_current(queryset: QuerySet[Any], *current: int | None) -> QuerySet[Any]:
    """Leave hidden records out, except those the record being edited uses."""
    return queryset.filter(Q(hidden=False) | Q(pk__in=[pk for pk in current if pk]))


def grouped_by_kind(accounts: QuerySet[Account]) -> list[Any]:
    """Account choices under one heading per kind, in the kinds' usual order."""
    by_kind: dict[str, list[tuple[int, str]]] = {kind: [] for kind in Kind.values}
    for account in accounts.order_by(Lower("name")):
        by_kind[account.kind].append((account.pk, account.name))
    groups = [(Kind(kind).label, choices) for kind, choices in by_kind.items()]
    return [("", "---------"), *[group for group in groups if group[1]]]


class TransactionForm(forms.ModelForm[Transaction]):
    """The Transaction's own fields: date, Party and description."""

    class Meta:
        model = Transaction
        fields = ("date", "party", "description")
        widgets: ClassVar = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial["date"] = timezone.localdate()
        party = cast("forms.ModelChoiceField[Party]", self.fields["party"])
        party.queryset = visible_or_current(
            Party.objects.order_by(Lower("name")), self.instance.party_id
        )

    def clean_date(self) -> Any:  # noqa: ANN401
        """Reject a date after today."""
        when = self.cleaned_data["date"]
        if when > timezone.localdate():
            msg = "The date cannot be after today."
            raise forms.ValidationError(msg)
        return when

    def check_opening_balances(self, splits: Iterable[Split]) -> bool:
        """Reject a date before the Opening Balance date of any Account used."""
        when = self.cleaned_data["date"]
        for split in splits:
            for account in (split.from_account, split.to_account):
                started = account.opening_balance_date
                if started and when < started:
                    self.add_error(
                        "date",
                        "The date cannot be before the Opening Balance date of "
                        f"{account} ({date_format(started, 'j M Y')}).",
                    )
                    return False
        return True


class SplitForm(forms.ModelForm[Split]):
    """One Split: an amount from one Account to another."""

    class Meta:
        model = Split
        fields = ("from_account", "to_account", "amount", "tags")
        labels: ClassVar = {"from_account": "From", "to_account": "To"}
        widgets: ClassVar = {"tags": forms.CheckboxSelectMultiple}

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
        applied = self.instance.tags.all() if self.instance.pk else []
        tags = cast("forms.ModelMultipleChoiceField[Tag]", self.fields["tags"])
        tags.queryset = visible_or_current(
            Tag.objects.order_by(Lower("name")), *(tag.pk for tag in applied)
        )

    def clean(self) -> dict[str, Any]:
        """Enforce the direction rules between the two Accounts."""
        super().clean()
        cleaned = self.cleaned_data
        source, destination = cleaned.get("from_account"), cleaned.get("to_account")
        if source and destination and (error := direction_error(source, destination)):
            raise forms.ValidationError(error)
        return cleaned


class BaseSplitFormSet(forms.BaseInlineFormSet[Split, Transaction, SplitForm]):
    """The Split rows of one Transaction, at least one of them kept."""

    default_error_messages: ClassVar = {
        **forms.BaseInlineFormSet.default_error_messages,
        "too_few_forms": "Add at least one Split.",
    }


SplitFormSet = forms.inlineformset_factory(
    Transaction,
    Split,
    form=SplitForm,
    formset=BaseSplitFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)


def kept_splits(
    formset: forms.BaseInlineFormSet[Split, Transaction, SplitForm],
) -> list[Split]:
    """The Splits a valid formset will save: filled in and not removed."""
    return [
        form.instance
        for form in formset.forms
        if form.cleaned_data and form not in formset.deleted_forms
    ]
