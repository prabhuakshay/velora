"""Investment Import and Export pages: upload, preview, confirm, download."""

from typing import TYPE_CHECKING

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.investments import importing
from apps.investments.export import events_csv, template_csv
from apps.investments.tasks import queue_backfill
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


class UploadForm(forms.Form):
    """The CSV file to preview."""

    file = forms.FileField(label="CSV file")

    def clean_file(self) -> str:
        """The file's text; it must be UTF-8."""
        try:
            return str(self.cleaned_data["file"].read().decode("utf-8-sig"))
        except UnicodeDecodeError as error:
            message = "Save the file as a UTF-8 CSV and upload it again."
            raise forms.ValidationError(message) from error


class ConfirmForm(forms.Form):
    """The previewed file's text, sent back to apply it."""

    text = forms.CharField(widget=forms.HiddenInput, strip=False)


def _preview(
    request: HttpRequest, text: str, result: importing.ImportResult
) -> HttpResponseBase:
    return render(
        request,
        "investments/import_preview.html",
        {"result": result, "confirm": ConfirmForm(initial={"text": text})},
    )


@login_required
@blocked_in_privacy_mode
def investment_import(request: HttpRequest) -> HttpResponseBase:
    """Upload an Investment Import CSV and preview it; nothing changes yet."""
    form = UploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        text = form.cleaned_data["file"]
        return _preview(request, text, importing.check(text))
    return render(request, "investments/import.html", {"form": form})


@login_required
@require_POST
@blocked_in_privacy_mode
def investment_import_confirm(request: HttpRequest) -> HttpResponseBase:
    """Apply the previewed file in one go, or show again why it can't be."""
    form = ConfirmForm(request.POST)
    if not form.is_valid():
        return redirect("investment_import")
    text = form.cleaned_data["text"]
    result = importing.apply(text)
    if not result.can_confirm:
        return _preview(request, text, result)
    if result.valid:
        queue_backfill()
    messages.success(
        request,
        f"Imported {len(result.valid)} Investment Events; skipped "
        f"{len(result.duplicates)} already recorded.",
    )
    return redirect("investments_overview")


@login_required
def investment_import_template(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    """Download the import template with an example row of every type."""
    return template_csv()


@login_required
@blocked_in_privacy_mode
def investment_export(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    """Download every Investment Event in the import format."""
    return events_csv()
