from typing import TYPE_CHECKING, Any

from django import forms
from django.conf import settings
from django.db.models.functions import Lower

from apps.budget.models import Category, CategoryGroup
from apps.icons.templatetags.icons import read_icon

if TYPE_CHECKING:
    from apps.users.models import User


class CategoryGroupForm(forms.ModelForm[CategoryGroup]):
    class Meta:
        model = CategoryGroup
        fields = ("name", "kind", "hidden")

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


class CategoryForm(forms.ModelForm[Category]):
    class Meta:
        model = Category
        fields = ("group", "name", "icon", "description", "color", "hidden")

    def __init__(self, *args: object, owner: User, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        group_field = self.fields["group"]
        group_field.queryset = CategoryGroup.objects.filter(  # type: ignore[attr-defined]
            owner=owner
        ).order_by(Lower("name"))
        self.fields["icon"].required = False

    def clean_icon(self) -> str:
        icon: str = self.cleaned_data["icon"].strip() or "tag"
        if read_icon(str(settings.LUCIDE_ICON_DIR), icon) is None:
            msg = "Unknown icon name."
            raise forms.ValidationError(msg)
        return icon

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        group, name = cleaned.get("group"), cleaned.get("name")
        if group and name:
            clash = Category.objects.filter(group=group, name__iexact=name)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("name", "A category with this name already exists.")
        return cleaned
