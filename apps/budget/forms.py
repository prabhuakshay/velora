"""Forms for categories and expense accounts."""

from typing import Any, ClassVar, override

from django import forms
from django.conf import settings
from django.db.models.functions import Lower

from apps.budget.icons import CURATED_ICONS, read_icon
from apps.budget.models import SWATCH_CLASSES, Category, ExpenseAccount


class CategoryForm(forms.ModelForm[Category]):
    """Create or edit a category."""

    class Meta:
        model = Category
        fields = ("kind", "name", "icon", "description", "color", "hidden")

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["icon"].required = False

    @property
    def icon_picker(self) -> dict[str, Any]:
        """Curated icons plus the current one, if it is not curated."""
        selected = str(self["icon"].value() or "tag")
        icons = list(CURATED_ICONS)
        if selected not in icons:
            icons.insert(0, selected)
        return {"icons": icons, "selected": selected}

    @property
    def color_swatches(self) -> list[tuple[str, str, bool]]:
        """Each colour's name, swatch class and whether it is selected."""
        selected = self["color"].value()
        return [
            (name, swatch, name == selected) for name, swatch in SWATCH_CLASSES.items()
        ]

    def clean_icon(self) -> str:
        """Default a blank icon to the tag and reject names with no SVG."""
        icon: str = self.cleaned_data["icon"].strip() or "tag"
        if read_icon(str(settings.LUCIDE_ICON_DIR), icon) is None:
            msg = "Unknown icon name."
            raise forms.ValidationError(msg)
        return icon

    @override
    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        kind, name = cleaned.get("kind"), cleaned.get("name")
        if kind and name:
            clash = Category.objects.filter(kind=kind, name__iexact=name)
            if self.instance.pk:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("name", "A category with this name already exists.")
        return cleaned


class ExpenseAccountForm(forms.ModelForm[ExpenseAccount]):
    """Create or edit an expense account."""

    class Meta:
        model = ExpenseAccount
        fields = ("name", "notes", "hidden")
        widgets: ClassVar = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean_name(self) -> str:
        """Reject a name already in use, ignoring case."""
        name: str = self.cleaned_data["name"]
        clash = ExpenseAccount.objects.filter(name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            msg = "An expense account with this name already exists."
            raise forms.ValidationError(msg)
        return name


class ExpenseAccountMergeForm(forms.Form):
    """Pick another expense account to merge into."""

    target = forms.ModelChoiceField(
        queryset=ExpenseAccount.objects.none(), label="Merge into", empty_label=None
    )

    def __init__(self, *args: object, source: ExpenseAccount, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["target"].queryset = (  # type: ignore[attr-defined]
            ExpenseAccount.objects.exclude(pk=source.pk).order_by(Lower("name"))
        )
