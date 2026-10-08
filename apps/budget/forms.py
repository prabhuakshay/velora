from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.conf import settings
from django.db.models.functions import Lower

from apps.budget.icon_picker import CURATED_ICONS
from apps.budget.models import SWATCH_CLASSES, Category, ExpenseAccount
from apps.icons.templatetags.icons import read_icon

if TYPE_CHECKING:
    from apps.users.models import User


class CategoryForm(forms.ModelForm[Category]):
    class Meta:
        model = Category
        fields = ("kind", "name", "icon", "description", "color", "hidden")

    def __init__(self, *args: object, owner: User, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.owner = owner
        self.fields["icon"].required = False

    @property
    def icon_picker(self) -> dict[str, Any]:
        selected = str(self["icon"].value() or "tag")
        icons = list(CURATED_ICONS)
        if selected not in icons:
            icons.insert(0, selected)
        return {"icons": icons, "selected": selected}

    @property
    def color_swatches(self) -> list[tuple[str, str, bool]]:
        selected = self["color"].value()
        return [
            (name, swatch, name == selected) for name, swatch in SWATCH_CLASSES.items()
        ]

    def clean_icon(self) -> str:
        icon: str = self.cleaned_data["icon"].strip() or "tag"
        if read_icon(str(settings.LUCIDE_ICON_DIR), icon) is None:
            msg = "Unknown icon name."
            raise forms.ValidationError(msg)
        return icon

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        kind, name = cleaned.get("kind"), cleaned.get("name")
        if kind and name:
            clash = Category.objects.filter(
                owner=self.owner, kind=kind, name__iexact=name
            )
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("name", "A category with this name already exists.")
        return cleaned

    def save(self, commit: bool = True) -> Category:  # noqa: FBT001, FBT002
        self.instance.owner = self.owner
        return super().save(commit=commit)


class ExpenseAccountForm(forms.ModelForm[ExpenseAccount]):
    class Meta:
        model = ExpenseAccount
        fields = ("name", "notes", "hidden")
        widgets: ClassVar = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args: object, owner: User, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.owner = owner

    def clean_name(self) -> str:
        name: str = self.cleaned_data["name"]
        clash = ExpenseAccount.objects.filter(owner=self.owner, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            msg = "An expense account with this name already exists."
            raise forms.ValidationError(msg)
        return name

    def save(self, commit: bool = True) -> ExpenseAccount:  # noqa: FBT001, FBT002
        self.instance.owner = self.owner
        return super().save(commit=commit)


class ExpenseAccountMergeForm(forms.Form):
    target = forms.ModelChoiceField(
        queryset=ExpenseAccount.objects.none(), label="Merge into", empty_label=None
    )

    def __init__(self, *args: object, source: ExpenseAccount, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["target"].queryset = (  # type: ignore[attr-defined]
            ExpenseAccount.objects.filter(owner_id=source.owner_id)
            .exclude(pk=source.pk)
            .order_by(Lower("name"))
        )
