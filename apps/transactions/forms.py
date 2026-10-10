"""Forms for recording a Transaction and its Splits."""

from typing import TYPE_CHECKING, Any, ClassVar, cast

from django import forms
from django.db.models import Count, Q, QuerySet, Sum
from django.db.models.functions import Lower
from django.utils import timezone

from apps.accounts.models import Account
from apps.classification.models import Party, Tag
from apps.transactions.attachment_rules import (
    MAX_ATTACHMENTS,
    MAX_TOTAL_BYTES,
    MAX_TOTAL_MB,
    checked_content_type,
)
from apps.transactions.models import Split, Transaction
from apps.transactions.split_rules import (
    direction_error,
    opening_balance_error,
    shared_account_error,
)

if TYPE_CHECKING:
    from datetime import date

    from django.core.files.uploadedfile import UploadedFile

Kind = Account.Kind


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


def offer_parties(form: forms.ModelForm[Any]) -> None:
    """Offer the visible Parties by name, and the one the record already has."""
    party = cast("forms.ModelChoiceField[Party]", form.fields["party"])
    party.queryset = visible_or_current(
        Party.objects.order_by(Lower("name")), form.instance.party_id
    )


def offer_accounts(form: forms.ModelForm[Any]) -> None:
    """Offer the visible Accounts by kind, and those the Split already uses."""
    accounts = visible_or_current(
        Account.objects.all(),
        form.instance.from_account_id,
        form.instance.to_account_id,
    )
    for name in ("from_account", "to_account"):
        field = cast("forms.ModelChoiceField[Account]", form.fields[name])
        field.queryset = accounts
        field.choices = grouped_by_kind(accounts)


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


TOO_LARGE = f"A Transaction's Attachments can total at most {MAX_TOTAL_MB} MB."


class TransactionForm(forms.ModelForm[Transaction]):
    """The Transaction's own fields: date, Party and description.

    Also takes the files to add as Attachments, which the caller stores once
    the Transaction is saved.
    """

    attachments = MultipleFileField(required=False)

    class Meta:
        model = Transaction
        fields = ("date", "party", "description")
        error_messages: ClassVar = {
            "party": {"invalid_choice": "That Party is inactive or no longer exists."}
        }
        widgets: ClassVar = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.initial["date"] = timezone.localdate()
        self.existing = (
            self.instance.attachments.aggregate(count=Count("pk"), size=Sum("size"))
            if self.instance.pk
            else {"count": 0, "size": 0}
        )
        # The browser checks the total before uploading; the server only refuses
        # once the whole request body has arrived.
        self.fields["attachments"].widget.attrs.update(
            {
                "data-max-total-bytes": MAX_TOTAL_BYTES,
                "data-existing-bytes": self.existing["size"] or 0,
                "data-too-large": TOO_LARGE,
            }
        )
        offer_parties(self)

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
        existing = self.existing
        if existing["count"] + len(files) > MAX_ATTACHMENTS:
            errors.append(
                f"A Transaction can have at most {MAX_ATTACHMENTS} Attachments."
            )
        total = (existing["size"] or 0) + sum(file.size or 0 for file in files)
        if total > MAX_TOTAL_BYTES:
            errors.append(TOO_LARGE)
        if errors:
            raise forms.ValidationError(errors)
        return checked


class SplitForm(forms.ModelForm[Split]):
    """One Split: an amount from one Account to another."""

    class Meta:
        model = Split
        fields = ("from_account", "to_account", "amount", "tags")
        labels: ClassVar = {"from_account": "From", "to_account": "To"}
        error_messages: ClassVar = {
            name: {"invalid_choice": "That Account is inactive or no longer exists."}
            for name in ("from_account", "to_account")
        }
        widgets: ClassVar = {"tags": forms.CheckboxSelectMultiple}

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        offer_accounts(self)
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
        if error := shared_account_error(
            (data.get("from_account"), data.get("to_account")) for data in kept
        ):
            raise forms.ValidationError(error)

    def check_opening_balances(self, when: date) -> bool:
        """Reject a date before the Opening Balance date of any Account used.

        Each kept Split row gets an error per Account of it that opens later.
        """
        valid = True
        for form in self.kept_forms():
            split = form.instance
            for account in (split.from_account, split.to_account):
                if error := opening_balance_error(account, when):
                    form.add_error(None, error)
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
