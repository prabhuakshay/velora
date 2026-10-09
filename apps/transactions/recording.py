"""Validating and saving a Transaction with its Splits and Attachments."""

from typing import TYPE_CHECKING, Any, cast

from django.db import transaction as db_transaction

from apps.transactions.attachments import remove_files, save_attachments
from apps.transactions.forms import BaseSplitFormSet, SplitFormSet, TransactionForm

if TYPE_CHECKING:
    from apps.transactions.models import Attachment, Transaction


class TransactionForms:
    """The Transaction form and its Split formset, checked and saved as one.

    The only way a Transaction is recorded, so every route in applies the
    same rules: the form, the Split formset and the Opening Balance check.
    """

    def __init__(
        self,
        data: Any = None,  # noqa: ANN401
        files: Any = None,  # noqa: ANN401
        *,
        instance: Transaction,
    ) -> None:
        self.form = TransactionForm(data, files, instance=instance)
        self.formset = cast("BaseSplitFormSet", SplitFormSet(data, instance=instance))

    def is_valid(self) -> bool:
        """Whether the Transaction and its Splits can be saved."""
        # Validate both so errors show on the Transaction and its Splits at once.
        valid = all([self.form.is_valid(), self.formset.is_valid()])
        return valid and self.formset.check_opening_balances(
            self.form.cleaned_data["date"]
        )

    def errors(self) -> list[str]:
        """Every error, as a sentence that says where it is."""
        found: list[str] = [
            f"{self.form[name].label}: {error}" if name != "__all__" else str(error)
            for name, errors in self.form.errors.items()
            for error in errors
        ]
        found.extend(str(error) for error in self.formset.non_form_errors())
        for number, split in enumerate(self.formset.forms, start=1):
            for name, errors in split.errors.items():
                where = (
                    f"Split {number}"
                    if name == "__all__"
                    else f"Split {number} {split[name].label}"
                )
                found.extend(f"{where}: {error}" for error in errors)
        return found

    def save(self) -> Transaction:
        """Save the valid Transaction, its Splits and its new Attachments.

        Call outside any atomic block when there are Attachments: the block
        here must be the real commit, so a failed commit is seen and the new
        files can be removed.
        """
        saved: list[Attachment] = []
        try:
            with db_transaction.atomic():
                self.formset.instance = self.form.save()
                self.formset.save()
                saved = save_attachments(
                    self.formset.instance, self.form.cleaned_data["attachments"]
                )
        except Exception:
            # Rolling back the rows can't take the files back out of storage.
            remove_files(saved)
            raise
        return self.formset.instance
