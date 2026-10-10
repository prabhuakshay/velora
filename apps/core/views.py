"""View helpers shared by apps that manage named, hideable records."""

from typing import TYPE_CHECKING, Any, Protocol

from django.contrib import messages
from django.core.paginator import Page, Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django import forms
    from django.db.models import QuerySet
    from django.forms import BaseFormSet
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

PAGE_SIZE = 25


class Hideable(Protocol):
    """A record that can be hidden from its default list."""

    hidden: bool

    def save(self) -> None:
        """Persist the record."""


def paginate(request: HttpRequest, items: QuerySet | Sequence[object]) -> Page:  # type: ignore[type-arg]
    """The page of the items named by the request's page parameter."""
    return Paginator(items, PAGE_SIZE).get_page(request.GET.get("page"))


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
    request: HttpRequest,
    obj: object,
    noun: str,
    merge_url: str,
    *,
    used_by: str = "Transactions",
) -> HttpResponseBase:
    """Explain why an in-use record cannot be deleted, then go to its Merge."""
    messages.info(
        request,
        f"{obj} is used by {used_by}, so it cannot be deleted. Merge it into "
        f"another {noun}, or hide it to keep it off new Transactions.",
    )
    return redirect(merge_url)


def blank_split_row(
    request: HttpRequest, formset_class: type[BaseFormSet[Any]]
) -> HttpResponse:
    """A blank row of the formset for the form's "add split" control."""
    total = request.GET.get("splits-TOTAL_FORMS", "")
    index = int(total) if total.isdecimal() else 0
    split = formset_class().empty_form
    split.prefix = f"splits-{index}"
    return render(
        request,
        "transactions/split_row_added.html",
        {"split": split, "total": index + 1},
    )
