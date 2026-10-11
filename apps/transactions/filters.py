"""Searching and filtering the Transaction list."""

from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.db.models import Q
from django.db.models.functions import Lower

from apps.accounts.models import Account
from apps.classification.models import Party, Tag
from apps.transactions.forms import grouped_by_kind
from apps.transactions.models import Split

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.transactions.models import Transaction

# The filters that apply to the Transaction itself; the rest go through its Splits.
LOOKUPS = {
    "party": "party",
    "start": "date__gte",
    "end": "date__lte",
    "min_total": "total__gte",
    "max_total": "total__lte",
}


class TransactionFilterForm(forms.Form):
    """Narrow the Transactions by text, Account, Party, Tag, date and total.

    Hidden Accounts, Parties and Tags are offered too, as their past
    Transactions are still worth finding.
    """

    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.SearchInput(
            attrs={"placeholder": "Search description, Party, Account or Tag"}
        ),
    )
    account = forms.ModelChoiceField(queryset=Account.objects.all(), required=False)
    party = forms.ModelChoiceField(
        queryset=Party.objects.order_by(Lower("name")), required=False
    )
    tag = forms.ModelChoiceField(
        queryset=Tag.objects.order_by(Lower("name")), required=False
    )
    start = forms.DateField(
        required=False, label="From", widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(
        required=False, label="To", widget=forms.DateInput(attrs={"type": "date"})
    )
    min_total = forms.DecimalField(required=False, label="Min amount", min_value=0)
    max_total = forms.DecimalField(required=False, label="Max amount", min_value=0)

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        account = cast("forms.ModelChoiceField[Account]", self.fields["account"])
        account.choices = grouped_by_kind(Account.objects.all())

    @property
    def active(self) -> dict[str, Any]:
        """The valid filters that were filled in; invalid ones are ignored."""
        self.is_valid()
        return {
            name: value
            for name, value in getattr(self, "cleaned_data", {}).items()
            if value not in (None, "")
        }

    @property
    def narrowing(self) -> int:
        """How many filters beyond the search box are active."""
        return len(self.active.keys() - {"q"})

    def apply(self, transactions: QuerySet[Transaction]) -> QuerySet[Transaction]:
        """The Transactions matching every active filter."""
        active = self.active
        # Split filters go through subqueries, as joining splits would
        # multiply the total annotated on each Transaction.
        if q := active.get("q"):
            matching_splits = Split.objects.filter(
                Q(from_account__name__icontains=q)
                | Q(to_account__name__icontains=q)
                | Q(tags__name__icontains=q)
            )
            transactions = transactions.filter(
                Q(description__icontains=q)
                | Q(party__name__icontains=q)
                | Q(pk__in=matching_splits.values("transaction"))
            )
        if account := active.get("account"):
            touching = Split.objects.filter(
                Q(from_account=account) | Q(to_account=account)
            )
            transactions = transactions.filter(pk__in=touching.values("transaction"))
        if tag := active.get("tag"):
            tagged = Split.objects.filter(tags=tag)
            transactions = transactions.filter(pk__in=tagged.values("transaction"))
        return transactions.filter(
            **{
                LOOKUPS[name]: value
                for name, value in active.items()
                if name in LOOKUPS
            }
        )
