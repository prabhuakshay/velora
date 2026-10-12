"""Views for managing Tags."""

from decimal import Decimal
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import OuterRef, Prefetch, Subquery, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.classification.activity import activity, party_shares
from apps.classification.forms import TagForm
from apps.classification.merge import delete_tag, merge_tag
from apps.classification.models import Tag, spent
from apps.classification.views.common import (
    SORT_LABELS,
    chart,
    merge_page,
    ordering,
    saved,
    set_hidden,
    sort_from,
    tabs,
    today,
)
from apps.core.views import paginate, save_unique_name
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


@login_required
def tag_list(request: HttpRequest) -> HttpResponse:
    """List Tags with what was spent or earned under each, all time.

    Hidden ones are listed apart, folded away.
    """
    sort = sort_from(request)
    listed = list(Tag.objects.with_usage().order_by(*ordering(sort)))
    shown = [tag for tag in listed if not tag.hidden]
    # Each Split once, however many visible Tags it carries.
    tagged = Split.objects.filter(
        pk__in=Split.objects.filter(tags__hidden=False).values("pk")
    )
    this_month = tagged.filter(transaction__date__gte=today().replace(day=1))
    total = Sum(spent(), default=Decimal(0))
    return render(
        request,
        "classification/tag_list.html",
        {
            "tabs": tabs("tag"),
            "tags": shown,
            "hidden": [tag for tag in listed if tag.hidden],
            "spent": tagged.aggregate(total=total)["total"],
            "this_month": this_month.aggregate(total=total)["total"],
            "unused": sum(1 for t in shown if not t.split_count),
            "sort": sort,
            "sorts": SORT_LABELS,
        },
    )


def _tagged_transactions(tag: Tag) -> QuerySet[Transaction]:
    """The Transactions with a Split carrying the Tag, and those Splits' total."""
    tagged = Split.objects.filter(tags=tag)
    return (
        Transaction.objects.filter(pk__in=tagged.values("transaction"))
        .select_related("party")
        .prefetch_related(
            Prefetch(
                "splits",
                queryset=Split.objects.select_related("from_account", "to_account"),
            )
        )
        .annotate(
            total=Sum("splits__amount"),
            # A subquery, as joining Tags here would multiply the total.
            tagged=Subquery(
                tagged.filter(transaction=OuterRef("pk"))
                .order_by()
                .values("transaction")
                .annotate(sum=Sum("amount"))
                .values("sum")
            ),
        )
        .order_by("-date", "-pk")
    )


@login_required
def tag_transactions(request: HttpRequest, pk: int) -> HttpResponse:
    """A Tag's money all time and by month, and its Transactions, newest first."""
    tag = get_object_or_404(Tag, pk=pk)
    splits = Split.objects.filter(tags=tag)
    result = activity(splits, today())
    return render(
        request,
        "classification/tag_detail.html",
        {
            "tag": tag,
            "activity": result,
            "parties": party_shares(splits, earns=result.earns),
            "bars": chart(request, result),
            "page": paginate(request, _tagged_transactions(tag)),
            "split_count": splits.count(),
            "here": request.get_full_path(),
        },
    )


@login_required
def tag_create(request: HttpRequest) -> HttpResponseBase:
    """Create a tag."""
    form = TagForm(request.POST or None)
    if form.is_valid() and save_unique_name(form):
        saved(request, form.instance, editing=False)
        return redirect("tag_transactions", pk=form.instance.pk)
    return render(request, "classification/tag_form.html", {"form": form})


@login_required
def tag_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a tag."""
    tag = get_object_or_404(Tag, pk=pk)
    form = TagForm(request.POST or None, instance=tag)
    if form.is_valid() and save_unique_name(form):
        saved(request, tag, editing=True)
        return redirect("tag_transactions", pk=pk)
    return render(request, "classification/tag_form.html", {"form": form, "tag": tag})


@login_required
@require_POST
def tag_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Hide a tag from the list and from new Splits."""
    tag = get_object_or_404(Tag, pk=pk)
    return set_hidden(request, tag, "tag", hidden=True)


@login_required
@require_POST
def tag_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden tag in the list again."""
    tag = get_object_or_404(Tag, pk=pk)
    return set_hidden(request, tag, "tag", hidden=False)


@login_required
def tag_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a tag; one in use is removed from its Splits."""
    tag = get_object_or_404(Tag, pk=pk)
    if request.method == "POST":
        delete_tag(tag)
        messages.success(request, f"Deleted {tag}.")
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
        {
            "object": tag,
            "noun": "tag",
            "list_url": reverse("tag_transactions", args=[pk]),
        },
    )


@login_required
def tag_merge(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Choose a target, then Merge a tag into it."""
    tag = get_object_or_404(Tag, pk=pk)
    count = tag.splits.count()
    impact = f"{count} Split{pluralize(count)} will move."
    return merge_page(request, tag, merge_tag, "tag", impact)
