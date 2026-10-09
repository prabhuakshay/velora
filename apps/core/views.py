"""View helpers shared by apps that manage named, hideable records."""

from typing import TYPE_CHECKING, Protocol

from django.db import IntegrityError, transaction
from django.shortcuts import redirect

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase


class Hideable(Protocol):
    """A record that can be hidden from its default list."""

    hidden: bool

    def save(self) -> None:
        """Persist the record."""


def save_unique_name(form: forms.ModelForm) -> bool:  # type: ignore[type-arg]
    """Save, turning a concurrent duplicate name into a form error."""
    try:
        with transaction.atomic():
            form.save()
    except IntegrityError:
        form.add_error("name", "This name already exists.")
        return False
    return True


def set_hidden(
    request: HttpRequest, obj: Hideable, list_url: str, *, hidden: bool
) -> HttpResponseBase:
    """Hide or unhide, then redirect to the list keeping the show-hidden view."""
    obj.hidden = hidden
    obj.save()
    response = redirect(list_url)
    if request.GET.get("show_hidden") == "1":
        response["Location"] += "?show_hidden=1"
    return response
