"""Form pieces shared across apps."""

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


def clean_unique_name(
    form: forms.ModelForm[Any], others: QuerySet[Any], error: str
) -> str:
    """The form's name, unless one of the others has it already, ignoring case."""
    name: str = form.cleaned_data["name"]
    clash = others.filter(name__iexact=name)
    if form.instance.pk:
        clash = clash.exclude(pk=form.instance.pk)
    if clash.exists():
        raise forms.ValidationError(error)
    return name
