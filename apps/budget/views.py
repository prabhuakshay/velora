from typing import TYPE_CHECKING

from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Value, When
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render

from apps.budget.forms import CategoryGroupForm
from apps.budget.models import CategoryGroup

if TYPE_CHECKING:
    from django.db import models
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _own_groups(request: HttpRequest) -> models.QuerySet[CategoryGroup]:
    return CategoryGroup.objects.filter(owner_id=request.user.pk)


@login_required
def category_list(request: HttpRequest) -> HttpResponse:
    expense_first = Case(
        When(kind=CategoryGroup.Kind.EXPENSE, then=Value(0)),
        default=Value(1),
        output_field=IntegerField(),
    )
    groups = _own_groups(request).order_by(expense_first, Lower("name"))
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
    if request.method == "POST":
        group.delete()
        return redirect("category_list")
    return render(request, "budget/group_confirm_delete.html", {"group": group})
