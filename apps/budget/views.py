"""Views for managing categories and expense accounts."""

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.budget.activity import PAGE_SIZE, recent_entries
from apps.budget.forms import CategoryForm, ExpenseAccountForm, ExpenseAccountMergeForm
from apps.budget.icons import CURATED_ICONS, search_icons
from apps.budget.models import Category, ExpenseAccount

if TYPE_CHECKING:
    from django import forms
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase


def _saved(form: forms.ModelForm) -> bool:  # type: ignore[type-arg]
    """Save, turning a concurrent duplicate name into a form error."""
    try:
        with transaction.atomic():
            form.save()
    except IntegrityError:
        form.add_error("name", "This name already exists.")
        return False
    return True


@login_required
def category_list(request: HttpRequest) -> HttpResponse:
    """List categories by kind, with recent activity."""
    show_hidden = request.GET.get("show_hidden") == "1"
    categories = Category.objects.order_by(Lower("name"))
    if not show_hidden:
        categories = categories.filter(hidden=False)
    sections = [
        (kind.label, [c for c in categories if c.kind == kind])
        for kind in (Category.Kind.EXPENSE, Category.Kind.INCOME)
    ]
    context = {
        "sections": sections,
        "show_hidden": show_hidden,
        **_activity_context(0),
    }
    return render(request, "budget/category_list.html", context)


def _activity_context(offset: int) -> dict[str, object]:
    entries, has_more = recent_entries(offset)
    return {
        "entries": entries,
        "next_offset": offset + PAGE_SIZE if has_more else None,
    }


@login_required
def category_activity(request: HttpRequest) -> HttpResponse:
    """Render the next page of the activity feed."""
    try:
        offset = max(int(request.GET.get("offset", "0")), 0)
    except ValueError:
        offset = 0
    return render(request, "budget/activity_items.html", _activity_context(offset))


@login_required
def category_create(request: HttpRequest) -> HttpResponseBase:
    """Create a category."""
    form = CategoryForm(request.POST or None)
    if form.is_valid() and _saved(form):
        return redirect("category_list")
    return render(request, "budget/category_form.html", {"form": form})


@login_required
def category_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a category."""
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(
        request.POST or None,
        instance=category,
    )
    if form.is_valid() and _saved(form):
        return redirect("category_list")
    return render(
        request, "budget/category_form.html", {"form": form, "category": category}
    )


@login_required
def category_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a category."""
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        category.delete()
        return redirect("category_list")
    return render(
        request, "budget/category_confirm_delete.html", {"category": category}
    )


@login_required
def icon_search(request: HttpRequest) -> HttpResponse:
    """Render icons matching the search, keeping the selected one."""
    selected = request.GET.get("icon", "")
    icons = search_icons(str(settings.LUCIDE_ICON_DIR), request.GET.get("q", ""))
    if selected and selected not in CURATED_ICONS and selected not in icons:
        icons.insert(0, selected)
    return render(
        request, "budget/_icon_options.html", {"icons": icons, "selected": selected}
    )


def _set_hidden(
    request: HttpRequest,
    obj: Category | ExpenseAccount,
    *,
    hidden: bool,
    list_url: str = "category_list",
) -> HttpResponseBase:
    obj.hidden = hidden
    obj.save()
    response = redirect(list_url)
    if request.GET.get("show_hidden") == "1":
        response["Location"] += "?show_hidden=1"
    return response


@login_required
@require_POST
def category_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Hide a category from the default list."""
    return _set_hidden(request, get_object_or_404(Category, pk=pk), hidden=True)


@login_required
@require_POST
def category_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden category in the default list again."""
    return _set_hidden(request, get_object_or_404(Category, pk=pk), hidden=False)


@login_required
def expense_account_list(request: HttpRequest) -> HttpResponse:
    """List expense accounts by name."""
    show_hidden = request.GET.get("show_hidden") == "1"
    expense_accounts = ExpenseAccount.objects.order_by(Lower("name"))
    if not show_hidden:
        expense_accounts = expense_accounts.filter(hidden=False)
    context = {"expense_accounts": expense_accounts, "show_hidden": show_hidden}
    return render(request, "budget/expense_account_list.html", context)


@login_required
def expense_account_create(request: HttpRequest) -> HttpResponseBase:
    """Create an expense account."""
    form = ExpenseAccountForm(request.POST or None)
    if form.is_valid() and _saved(form):
        return redirect("expense_account_list")
    return render(request, "budget/expense_account_form.html", {"form": form})


@login_required
def expense_account_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit an expense account."""
    expense_account = get_object_or_404(ExpenseAccount, pk=pk)
    form = ExpenseAccountForm(
        request.POST or None,
        instance=expense_account,
    )
    if form.is_valid() and _saved(form):
        return redirect("expense_account_list")
    return render(
        request,
        "budget/expense_account_form.html",
        {"form": form, "expense_account": expense_account},
    )


@login_required
@require_POST
def expense_account_hide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Hide an expense account from the default list."""
    expense_account = get_object_or_404(ExpenseAccount, pk=pk)
    return _set_hidden(
        request, expense_account, hidden=True, list_url="expense_account_list"
    )


@login_required
@require_POST
def expense_account_unhide(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Show a hidden expense account in the default list again."""
    expense_account = get_object_or_404(ExpenseAccount, pk=pk)
    return _set_hidden(
        request, expense_account, hidden=False, list_url="expense_account_list"
    )


@login_required
def expense_account_merge(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Merge an expense account into another."""
    source = get_object_or_404(ExpenseAccount, pk=pk)
    form = ExpenseAccountMergeForm(request.POST or None, source=source)
    if form.is_valid():
        with transaction.atomic():
            source.delete()
        return redirect("expense_account_list")
    return render(
        request,
        "budget/expense_account_merge.html",
        {"form": form, "expense_account": source},
    )


@login_required
def expense_account_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete an expense account."""
    expense_account = get_object_or_404(ExpenseAccount, pk=pk)
    if request.method == "POST":
        expense_account.delete()
        return redirect("expense_account_list")
    return render(
        request,
        "budget/expense_account_confirm_delete.html",
        {"expense_account": expense_account},
    )
