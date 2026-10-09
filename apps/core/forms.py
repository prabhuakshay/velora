"""Forms shared by apps that Merge records."""

from typing import TYPE_CHECKING, Any

from django import forms

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet


class MergeForm(forms.Form):
    """Choose the target to Merge a source into, from the given targets."""

    target: forms.ModelChoiceField[Model] = forms.ModelChoiceField(
        queryset=None, label="Merge into"
    )

    def __init__(
        self, targets: QuerySet[Model], data: dict[str, Any] | None = None
    ) -> None:
        super().__init__(data)
        self.fields["target"].queryset = targets  # type: ignore[attr-defined]
