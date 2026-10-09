"""Forms for recording a Transaction and its Splits."""

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms
from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.formats import date_format

from apps.accounts.models import BALANCE_KINDS, Account
from apps.classification.models import Party, Tag
from apps.transactions.attachment_rules import (
    MAX_ATTACHMENTS,
    MAX_TOTAL_BYTES,
    MAX_TOTAL_MB,
    checked_content_type,
)
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from datetime import date

    from django.core.files.uploadedfile import UploadedFile

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


class MultipleFileInput(forms.ClearableFileInput):
    """A file picker that lets the user choose several files."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A file input that accepts several files at once."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        kwargs.setdefault("widget", MultipleFileInput)
        super().__init__(*args, **kwargs)

    def clean(self, data: Any, initial: Any = None) -> list[UploadedFile[bytes]]:  # noqa: ANN401
        """Clean each file on its own, giving a list."""
        files = data if isinstance(data, (list, tuple)) else [data]
        return [
            super(MultipleFileField, self).clean(file, initial)
            for file in files
            if file
        ]


class TransactionForm(forms.ModelForm[Transaction]):
    """The Transaction's own fields: date, Party and description.

    Also takes the files to add as Attachments, which the caller stores once
    the Transaction is saved.
    """

    attachments = MultipleFileField(required=False)

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

    def clean_attachments(self) -> list[tuple[UploadedFile[bytes], str]]:
        """Each file with its checked content type, rejecting any not allowed."""
        files: list[UploadedFile[bytes]] = self.cleaned_data["attachments"]
        checked, errors = [], []
        for file in files:
            try:
                checked.append((file, checked_content_type(file)))
            except forms.ValidationError as error:
                errors.extend(error.messages)
        if not files:
            return checked
        existing = (
            self.instance.attachments.aggregate(count=Count("pk"), size=Sum("size"))
            if self.instance.pk
            else {"count": 0, "size": 0}
        )
        if existing["count"] + len(files) > MAX_ATTACHMENTS:
            errors.append(
                f"A Transaction can have at most {MAX_ATTACHMENTS} Attachments."
            )
        total = (existing["size"] or 0) + sum(file.size or 0 for file in files)
        if total > MAX_TOTAL_BYTES:
            errors.append(
                f"A Transaction's Attachments can total at most {MAX_TOTAL_MB} MB."
            )
        if errors:
            raise forms.ValidationError(errors)
        return checked


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

    def kept_forms(self) -> list[SplitForm]:
        """The valid, filled-in Split rows that are not marked for removal."""
        # deleted_forms is empty until the whole formset is valid, so it cannot
        # be used while cleaning.
        return [
            form
            for form in self.forms
            if form.is_valid()
            and form.cleaned_data
            and not form.cleaned_data.get("DELETE")
        ]

    def clean(self) -> None:
        """Require every kept Split to share its From or its To Account."""
        super().clean()
        kept = [form.cleaned_data for form in self.kept_forms()]
        sources = {data.get("from_account") for data in kept}
        destinations = {data.get("to_account") for data in kept}
        if len(sources) > 1 and len(destinations) > 1:
            msg = "Splits must share a From or a To Account."
            raise forms.ValidationError(msg)

    def check_opening_balances(self, when: date) -> bool:
        """Reject a date before the Opening Balance date of any Account used.

        Each kept Split row gets an error per Account of it that opens later.
        """
        valid = True
        for form in self.kept_forms():
            split = form.instance
            for account in (split.from_account, split.to_account):
                if account.opens_after(when):
                    started = date_format(account.opening_balance_date, "j M Y")  # type: ignore[arg-type]
                    form.add_error(
                        None,
                        "The date cannot be before the Opening Balance date of "
                        f"{account} ({started}).",
                    )
                    valid = False
        return valid


SplitFormSet = forms.inlineformset_factory(
    Transaction,
    Split,
    form=SplitForm,
    formset=BaseSplitFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
)
