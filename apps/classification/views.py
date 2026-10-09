"""Views for managing parties and tags."""

from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.classification.forms import PartyForm, TagForm
from apps.classification.models import Party, Tag
from apps.core.views import save_unique_name, set_hidden

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


@login_required
def party_list(request: HttpRequest) -> HttpResponse:
    """List parties by name."""
    show_hidden = request.GET.get("show_hidden") == "1"
    parties = Party.objects.order_by(Lower("name"))
    if not show_hidden:
        parties = parties.filter(hidden=False)
    return render(
        request,
        "classification/party_list.html",
        {"parties": parties, "show_hidden": show_hidden},
    )


@login_required
def party_create(request: HttpRequest) -> HttpResponseBase:
    """Create a party."""
    form = PartyForm(request.POST or None)
    if form.is_valid() and save_unique_name(form):
        return redirect("party_list")
    return render(request, "classification/party_form.html", {"form": form})


@login_required
def party_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a party."""
    party = get_object_or_404(Party, pk=pk)
    form = PartyForm(request.POST or None, instance=party)
    if form.is_valid() and save_unique_name(form):
        return redirect("party_list")
    return render(
        request, "classification/party_form.html", {"form": form, "party": party}
    )


@login_required
@require_POST
def party_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Hide a party from the default list."""
    return set_hidden(
        request, get_object_or_404(Party, pk=pk), "party_list", hidden=True
    )


@login_required
@require_POST
def party_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden party in the default list again."""
    return set_hidden(
        request, get_object_or_404(Party, pk=pk), "party_list", hidden=False
    )


@login_required
def party_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a party."""
    party = get_object_or_404(Party, pk=pk)
    if request.method == "POST":
        party.delete()
        return redirect("party_list")
    return render(
        request,
        "classification/confirm_delete.html",
        {"object": party, "noun": "party", "list_url": "party_list"},
    )


@login_required
def tag_list(request: HttpRequest) -> HttpResponse:
    """List tags by name."""
    show_hidden = request.GET.get("show_hidden") == "1"
    tags = Tag.objects.order_by(Lower("name"))
    if not show_hidden:
        tags = tags.filter(hidden=False)
    return render(
        request,
        "classification/tag_list.html",
        {"tags": tags, "show_hidden": show_hidden},
    )


@login_required
def tag_create(request: HttpRequest) -> HttpResponseBase:
    """Create a tag."""
    form = TagForm(request.POST or None)
    if form.is_valid() and save_unique_name(form):
        return redirect("tag_list")
    return render(request, "classification/tag_form.html", {"form": form})


@login_required
def tag_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a tag."""
    tag = get_object_or_404(Tag, pk=pk)
    form = TagForm(request.POST or None, instance=tag)
    if form.is_valid() and save_unique_name(form):
        return redirect("tag_list")
    return render(request, "classification/tag_form.html", {"form": form, "tag": tag})


@login_required
@require_POST
def tag_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Hide a tag from the default list."""
    return set_hidden(request, get_object_or_404(Tag, pk=pk), "tag_list", hidden=True)


@login_required
@require_POST
def tag_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden tag in the default list again."""
    return set_hidden(request, get_object_or_404(Tag, pk=pk), "tag_list", hidden=False)


@login_required
def tag_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a tag."""
    tag = get_object_or_404(Tag, pk=pk)
    if request.method == "POST":
        tag.delete()
        return redirect("tag_list")
    return render(
        request,
        "classification/confirm_delete.html",
        {"object": tag, "noun": "tag", "list_url": "tag_list"},
    )
