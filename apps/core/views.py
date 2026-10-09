"""View helpers shared by apps that manage named, hideable records."""

from typing import TYPE_CHECKING, Protocol

from django.contrib import messages
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


def save_unique_name(
    form: forms.ModelForm,  # type: ignore[type-arg]
    error: str = "This name already exists.",
) -> bool:
    """Save, turning a concurrent duplicate name into a form error."""
    try:
        with transaction.atomic():
            form.save()
    except IntegrityError:
        form.add_error("name", error)
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


def redirect_in_use_to_merge(
    request: HttpRequest, obj: object, noun: str, merge_url: str
) -> HttpResponseBase:
    """Explain why an in-use record cannot be deleted, then go to its Merge."""
    messages.info(
        request,
        f"{obj} is used by Transactions, so it cannot be deleted. Merge it into "
        f"another {noun}, or hide it to keep it off new Transactions.",
    )
    return redirect(merge_url)
