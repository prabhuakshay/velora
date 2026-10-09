"""Views for managing parties and tags."""

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.classification.forms import PartyForm, TagForm
from apps.classification.merge import delete_tag, merge_party, merge_tag
from apps.classification.models import Party, Tag
from apps.core.forms import MergeForm
from apps.core.views import (
    paginate,
    redirect_in_use_to_merge,
    save_unique_name,
    set_hidden,
)
from apps.transactions.models import Split

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


@login_required
def party_list(request: HttpRequest) -> HttpResponse:
    """List parties by name, a page at a time."""
    show_hidden = request.GET.get("show_hidden") == "1"
    parties = Party.objects.order_by(Lower("name"))
    if not show_hidden:
        parties = parties.filter(hidden=False)
    return render(
        request,
        "classification/party_list.html",
        {"page": paginate(request, parties), "show_hidden": show_hidden},
    )


@login_required
def party_transactions(request: HttpRequest, pk: int) -> HttpResponse:
    """List a party's Transactions, newest first, a page at a time."""
    party = get_object_or_404(Party, pk=pk)
    transactions = party.transactions.prefetch_related(
        Prefetch(
            "splits",
            queryset=Split.objects.select_related("from_account", "to_account"),
        )
    ).order_by("-date", "-pk")
    return render(
        request,
        "classification/party_transactions.html",
        {"party": party, "page": paginate(request, transactions)},
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
        request, get_object_or_404(Party, pk=pk), reverse("party_list"), hidden=True
    )


@login_required
@require_POST
def party_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden party in the default list again."""
    return set_hidden(
        request, get_object_or_404(Party, pk=pk), reverse("party_list"), hidden=False
    )


@login_required
def party_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a party."""
    party = get_object_or_404(Party, pk=pk)
    if party.transactions.exists() or party.drafts.exists():
        merge_url = reverse("party_merge", args=[party.pk])
        return redirect_in_use_to_merge(
            request, party, "party", merge_url, used_by="Transactions or Drafts"
        )
    if request.method == "POST":
        party.delete()
        return redirect("party_list")
    return render(
        request,
        "confirm_delete.html",
        {"object": party, "noun": "party", "list_url": reverse("party_list")},
    )


@login_required
def party_merge(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Choose a target, then Merge a party into it."""
    party = get_object_or_404(Party, pk=pk)
    count = party.transactions.count()
    impact = f"{count} Transaction{pluralize(count)} will move."
    return _merge(request, party, merge_party, "party", impact)


@login_required
def tag_list(request: HttpRequest) -> HttpResponse:
    """List tags by name, a page at a time."""
    show_hidden = request.GET.get("show_hidden") == "1"
    tags = Tag.objects.order_by(Lower("name"))
    if not show_hidden:
        tags = tags.filter(hidden=False)
    return render(
        request,
        "classification/tag_list.html",
        {"page": paginate(request, tags), "show_hidden": show_hidden},
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
    return set_hidden(
        request, get_object_or_404(Tag, pk=pk), reverse("tag_list"), hidden=True
    )


@login_required
@require_POST
def tag_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden tag in the default list again."""
    return set_hidden(
        request, get_object_or_404(Tag, pk=pk), reverse("tag_list"), hidden=False
    )


@login_required
def tag_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a tag; one in use is removed from its Splits."""
    tag = get_object_or_404(Tag, pk=pk)
    if request.method == "POST":
        delete_tag(tag)
        return redirect("tag_list")
    if split_count := tag.splits.count():
        return render(
            request,
            "classification/tag_in_use.html",
            {"tag": tag, "split_count": split_count},
        )
    return render(
        request,
        "confirm_delete.html",
        {"object": tag, "noun": "tag", "list_url": reverse("tag_list")},
    )


@login_required
def tag_merge(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Choose a target, then Merge a tag into it."""
    tag = get_object_or_404(Tag, pk=pk)
    count = tag.splits.count()
    impact = f"{count} Split{pluralize(count)} will move."
    return _merge(request, tag, merge_tag, "tag", impact)


def _merge[R: (Party, Tag)](
    request: HttpRequest,
    source: R,
    merge: Callable[[R, R], None],
    noun: str,
    impact: str,
) -> HttpResponseBase:
    targets = type(source).objects.exclude(pk=source.pk).order_by(Lower("name"))
    form = MergeForm(targets, request.POST or None)
    list_url = reverse(f"{noun}_list")
    if form.is_valid():
        target = form.cleaned_data["target"]
        merge(source, target)
        messages.success(request, f"Merged {source} into {target}.")
        return redirect(list_url)
    return render(
        request,
        "merge.html",
        {
            "object": source,
            "noun": noun,
            "form": form,
            "impact": [impact],
            "list_url": list_url,
        },
    )
