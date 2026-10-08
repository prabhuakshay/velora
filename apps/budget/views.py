from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render

from apps.budget.forms import CategoryForm, CategoryGroupForm
from apps.budget.icon_picker import CURATED_ICONS
from apps.budget.models import Category, CategoryGroup
from apps.icons.search import search_icons

if TYPE_CHECKING:
    from django.db import models
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _own_groups(request: HttpRequest) -> models.QuerySet[CategoryGroup]:
    return CategoryGroup.objects.filter(owner_id=request.user.pk)


def _own_categories(request: HttpRequest) -> models.QuerySet[Category]:
    return Category.objects.filter(group__owner_id=request.user.pk).select_related(
        "group"
    )


@login_required
def category_list(request: HttpRequest) -> HttpResponse:
    expense_first = Case(
        When(kind=CategoryGroup.Kind.EXPENSE, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )
    groups = (
        _own_groups(request)
        .order_by(expense_first, Lower("name"))
        .prefetch_related(
            Prefetch("categories", Category.objects.order_by(Lower("name")))
        )
    )
    return render(request, "budget/category_list.html", {"groups": groups})


@login_required
def group_create(request: HttpRequest) -> HttpResponseBase:
    form = CategoryGroupForm(request.POST or None, owner=request.user)  # type: ignore[arg-type]
    if form.is_valid():
        form.save()
        return redirect("category_list")
    return render(request, "budget/group_form.html", {"form": form})


@login_required
def group_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    group = get_object_or_404(_own_groups(request), pk=pk)
    form = CategoryGroupForm(
        request.POST or None,
        instance=group,
        owner=request.user,  # type: ignore[arg-type]
    )
    if form.is_valid():
        form.save()
        return redirect("category_list")
    return render(request, "budget/group_form.html", {"form": form, "group": group})


@login_required
def group_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    group = get_object_or_404(_own_groups(request), pk=pk)
    category_count = group.categories.count()
    if request.method == "POST" and category_count == 0:
        group.delete()
        return redirect("category_list")
    context = {"group": group, "category_count": category_count}
    return render(
        request,
        "budget/group_confirm_delete.html",
        context,
        status=409 if request.method == "POST" else 200,
    )


@login_required
def category_create(request: HttpRequest) -> HttpResponseBase:
    form = CategoryForm(request.POST or None, owner=request.user)  # type: ignore[arg-type]
    if form.is_valid():
        form.save()
        return redirect("category_list")
    return render(request, "budget/category_form.html", {"form": form})


@login_required
def category_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    category = get_object_or_404(_own_categories(request), pk=pk)
    form = CategoryForm(
        request.POST or None,
        instance=category,
        owner=request.user,  # type: ignore[arg-type]
    )
    if form.is_valid():
        form.save()
        return redirect("category_list")
    return render(
        request, "budget/category_form.html", {"form": form, "category": category}
    )


@login_required
def category_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    category = get_object_or_404(_own_categories(request), pk=pk)
    if request.method == "POST":
        category.delete()
        return redirect("category_list")
    return render(
        request, "budget/category_confirm_delete.html", {"category": category}
    )


@login_required
def icon_search(request: HttpRequest) -> HttpResponse:
    selected = request.GET.get("icon", "")
    icons = search_icons(str(settings.LUCIDE_ICON_DIR), request.GET.get("q", ""))
    if selected and selected not in CURATED_ICONS and selected not in icons:
        icons.insert(0, selected)
    return render(
        request, "budget/_icon_options.html", {"icons": icons, "selected": selected}
    )
