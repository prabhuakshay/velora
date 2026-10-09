"""Forms for Accounts."""

from typing import ClassVar

from django import forms

from apps.accounts.models import Account


class AccountForm(forms.ModelForm[Account]):
    """Create or edit an Account; the kind comes from the instance, never the form."""

    class Meta:
        model = Account
        fields = ("name", "notes")
        widgets: ClassVar = {"notes": forms.Textarea(attrs={"rows": 3})}

    def clean_name(self) -> str:
        """Reject a name already in use within this kind, ignoring case."""
        name: str = self.cleaned_data["name"]
        kind = self.instance.kind
        clash = Account.objects.filter(kind=kind, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            msg = f"Another {Account.Kind(kind).label} Account already has this name."
            raise forms.ValidationError(msg)
        return name
