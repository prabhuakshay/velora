"""Editing a Draft that carries a Buy, Sell or Dividend."""

from typing import TYPE_CHECKING, Any, ClassVar

from django import forms
from django.contrib import messages
from django.db import transaction as db_transaction
from django.shortcuts import redirect, render

from apps.accounts.models import Account, AccountKind
from apps.investments.drafts import income_of, save_investment
from apps.investments.models import DraftInvestment
from apps.quick_add.forms import DraftEditForm
from apps.quick_add.models import Draft
from apps.quick_add.posting import DraftNotPostableError, post_draft, posting_problems

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http.response import HttpResponseBase

TRADE_FIELDS = ("units", "price", "charges")


class DraftInvestmentForm(forms.ModelForm[DraftInvestment]):
    """The Draft's Buy or Sell parts, or its Dividend and Income Account."""

    income_account = forms.ModelChoiceField(
        queryset=Account.objects.filter(kind=AccountKind.INCOME, hidden=False),
        required=False,
        help_text="The Income Account the Dividend is recorded from.",
    )

    class Meta:
        model = DraftInvestment
        fields = ("units", "price", "amount", "charges")
        help_texts: ClassVar = {
            "amount": "Units times Price, before charges; or the Dividend paid.",
            "charges": "Brokerage, STT, stamp duty and other charges.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        if self.instance.kind == DraftInvestment.Kind.DIVIDEND:
            for name in TRADE_FIELDS:
                del self.fields[name]
            self.initial["income_account"] = income_of(self.instance.draft)
        else:
            del self.fields["income_account"]

    def save(self, commit: bool = True) -> DraftInvestment:  # noqa: FBT001, FBT002, ARG002
        """Save the parts and the Draft's Split that moves their money."""
        save_investment(self.instance, self.cleaned_data.get("income_account"))
        return self.instance


def _page(
    request: HttpRequest,
    form: DraftEditForm,
    details: DraftInvestmentForm,
    posting_error: str = "",
) -> HttpResponseBase:
    return render(
        request,
        "investments/draft_form.html",
        {
            "form": form,
            "details": details,
            "draft": form.instance,
            "investment": details.instance,
            "posting_error": posting_error,
        },
    )


def _saved(form: DraftEditForm, details: DraftInvestmentForm) -> bool:
    """Save the edits, unless the Draft stopped waiting meanwhile."""
    draft = form.instance
    if not Draft.objects.select_for_update().filter(
        pk=draft.pk, status=Draft.Status.WAITING
    ):
        return False
    draft.posting_error = ""
    form.save()
    details.save()
    return True


def investment_draft_edit(request: HttpRequest, draft: Draft) -> HttpResponseBase:
    """Edit the waiting Draft's Investment Event, then save it or post it too."""
    form = DraftEditForm(request.POST or None, instance=draft)
    details = DraftInvestmentForm(request.POST or None, instance=draft.investment)
    if request.method != "POST":
        problems = posting_problems(draft)
        error = f"Can't post yet: {' '.join(problems)}" if problems else ""
        return _page(request, form, details, error)
    if not (form.is_valid() and details.is_valid()):
        return _page(request, form, details)
    with db_transaction.atomic():
        if not _saved(form, details):
            messages.info(
                request,
                "That Draft was already posted or rejected; nothing was saved.",
            )
        elif request.POST.get("action") == "post":
            return _post(request, draft)
    return redirect("draft_list")


def _post(request: HttpRequest, draft: Draft) -> HttpResponseBase:
    """Post the saved Draft, or show it again with why it can't be posted."""
    try:
        post_draft(draft)
    except DraftNotPostableError as error:
        draft.posting_error = str(error)
        draft.save(update_fields=["posting_error"])
        return _page(
            request,
            DraftEditForm(instance=draft),
            DraftInvestmentForm(instance=draft.investment),
            f"Couldn't post: {draft.posting_error}",
        )
    return redirect("draft_list")
