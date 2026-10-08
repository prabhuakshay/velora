from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.budget.forms import CategoryForm, CategoryGroupForm
from apps.budget.models import Category, CategoryGroup

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
    show_hidden = bool(request.GET.get("show_hidden"))
    groups = _own_groups(request)
    categories = Category.objects.order_by(Lower("name"))
    if not show_hidden:
        groups = groups.filter(hidden=False)
        categories = categories.filter(hidden=False)
    groups = groups.order_by(expense_first, Lower("name")).prefetch_related(
        Prefetch("categories", categories)
    )
    context = {"groups": groups, "show_hidden": show_hidden}
    return render(request, "budget/category_list.html", context)


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


def _set_hidden(obj: CategoryGroup | Category, *, hidden: bool) -> HttpResponseBase:
    obj.hidden = hidden
    obj.save()
    return redirect("category_list")


@login_required
@require_POST
def group_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    return _set_hidden(get_object_or_404(_own_groups(request), pk=pk), hidden=True)


@login_required
@require_POST
def group_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    return _set_hidden(get_object_or_404(_own_groups(request), pk=pk), hidden=False)


@login_required
@require_POST
def category_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    return _set_hidden(get_object_or_404(_own_categories(request), pk=pk), hidden=True)


@login_required
@require_POST
def category_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    return _set_hidden(get_object_or_404(_own_categories(request), pk=pk), hidden=False)
