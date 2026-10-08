from typing import TYPE_CHECKING

from django import forms

from apps.budget.models import CategoryGroup

if TYPE_CHECKING:
    from apps.users.models import User


class CategoryGroupForm(forms.ModelForm[CategoryGroup]):
    class Meta:
        model = CategoryGroup
        fields = ("name", "kind")

    def __init__(self, *args: object, owner: User, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.owner = owner

    def clean_name(self) -> str:
        name: str = self.cleaned_data["name"]
        clash = CategoryGroup.objects.filter(owner=self.owner, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            msg = "A group with this name already exists."
            raise forms.ValidationError(msg)
        return name

    def save(self, commit: bool = True) -> CategoryGroup:  # noqa: FBT001, FBT002
        self.instance.owner = self.owner
        return super().save(commit=commit)
