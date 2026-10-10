"""Forms for parties and tags."""

from typing import ClassVar

from django import forms

from apps.classification.models import SWATCH_CLASSES, Party, Tag
from apps.core.forms import clean_unique_name


class PartyForm(forms.ModelForm[Party]):
    """Create or edit a party."""

    class Meta:
        model = Party
        fields = ("name", "notes", "hidden")
        widgets: ClassVar = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean_name(self) -> str:
        """Reject a name already in use, ignoring case."""
        return clean_unique_name(
            self, Party.objects.all(), "A party with this name already exists."
        )


class TagForm(forms.ModelForm[Tag]):
    """Create or edit a tag."""

    class Meta:
        model = Tag
        fields = ("name", "color", "hidden")

    @property
    def color_swatches(self) -> list[tuple[str, str, bool]]:
        """Each colour's name, swatch class and whether it is selected."""
        selected = self["color"].value()
        return [
            (name, swatch, name == selected) for name, swatch in SWATCH_CLASSES.items()
        ]

    def clean_name(self) -> str:
        """Reject a name already in use, ignoring case."""
        return clean_unique_name(
            self, Tag.objects.all(), "A tag with this name already exists."
        )
