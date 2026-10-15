"""Views for recording and reviewing Transactions."""

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Count, OuterRef, Prefetch, Subquery, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from apps.accounts.models import Account
from apps.classification.models import Party, Tag
from apps.core.views import blank_split_row, paginate
from apps.transactions import cloudflare
from apps.transactions.bucket_stats import bucket_stats
from apps.transactions.export import transactions_csv
from apps.transactions.filters import TransactionFilterForm
from apps.transactions.forms import SplitFormSet
from apps.transactions.models import Attachment, Split, Transaction
from apps.transactions.recording import TransactionForms
from apps.transactions.storage_chart import storage_chart
from apps.transactions.storage_operations import count_operations
from apps.transactions.storage_stats import attachment_storage_stats
from apps.users.privacy_mode import blocked_in_privacy_mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import QuerySet
    from django.http import HttpRequest, HttpResponse
    from django.http.response import HttpResponseBase

    from apps.users.models import User

logger = logging.getLogger(__name__)


def _listed_transactions() -> QuerySet[Transaction]:
    """Every Transaction with its Splits and totals, newest first."""
    return (
        Transaction.objects.select_related("party", "investment_event__account")
        .prefetch_related(
            Prefetch(
                "splits",
                queryset=Split.objects.select_related(
                    "from_account", "to_account"
                ).prefetch_related("tags"),
            ),
            "attachments",
        )
        .annotate(
            total=Sum("splits__amount"),
            # A subquery, as joining attachments would multiply the splits total.
            attachment_count=Subquery(
                Attachment.objects.filter(transaction=OuterRef("pk"))
                .values("transaction")
                .annotate(count=Count("pk"))
                .values("count")
            ),
        )
        .order_by("-date", "-pk")
    )


@login_required
def transaction_list(request: HttpRequest) -> HttpResponse:
    """List the Transactions matching the filters, newest first, a page at a time."""
    filters = TransactionFilterForm(
        request.GET, privacy_mode=cast("User", request.user).privacy_mode
    )
    query = request.GET.copy()
    query.pop("page", None)
    today = timezone.localdate()
    return render(
        request,
        "transactions/transaction_list.html",
        {
            "today": today,
            "yesterday": today - timedelta(days=1),
            "page": paginate(request, filters.apply(_listed_transactions())),
            "filters": filters,
            "chips": filters.chips(request.GET),
            "extra_query": f"&{query.urlencode()}" if query else "",
            "export_query": f"?{query.urlencode()}" if query else "",
            "here": request.get_full_path(),
        },
    )


@login_required
def transaction_detail(request: HttpRequest, pk: int) -> HttpResponse:
    """One Transaction: the list's selected panel for htmx, else a full page."""
    template = (
        "transactions/_transaction_panel.html"
        if request.headers.get("HX-Request")
        else "transactions/transaction_detail.html"
    )
    return render(
        request,
        template,
        {
            "transaction": get_object_or_404(_listed_transactions(), pk=pk),
            "here": _return_url(request),
        },
    )


@login_required
@blocked_in_privacy_mode
def transaction_export(request: HttpRequest) -> HttpResponse:
    """Download the Transactions matching the filters as CSV."""
    filters = TransactionFilterForm(request.GET)
    return transactions_csv(filters.apply(_listed_transactions()))


def _return_url(request: HttpRequest) -> str:
    """Where to go once done: the page that sent the user here, else the list."""
    url = request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return reverse("transaction_list")


def _save_transaction_forms(
    request: HttpRequest,
    instance: Transaction,
    initial_splits: list[dict[str, Any]] | None = None,
) -> HttpResponseBase:
    """Show the create or edit form, saving the Transaction and Splits once valid."""
    forms = TransactionForms(
        request.POST or None,
        request.FILES or None,
        instance=instance,
        initial_splits=initial_splits,
    )
    if forms.is_valid():
        forms.save()
        return redirect(_return_url(request))
    form, formset = forms.form, forms.formset
    if request.FILES:
        form.add_error(
            "attachments",
            "Your files weren't saved because of the errors. Pick them again.",
        )
    return render(
        request,
        "transactions/transaction_form.html",
        {
            "form": form,
            "formset": formset,
            "transaction": instance if instance.pk else None,
            "return_url": _return_url(request),
        },
    )


# TransactionForms.save must be the real commit, so a failed commit is seen
# there and the new files can be removed.
@db_transaction.non_atomic_requests
@login_required
def transaction_create(request: HttpRequest) -> HttpResponseBase:
    """Record a new Transaction, starting from the Account, Party or Tag in the URL.

    The first Split starts at the Account, or ends there for an Expense Account,
    which money only goes to, and carries the Tag.
    """
    account = _from_query(request, "account", Account)
    party = _from_query(request, "party", Party)
    tag = _from_query(request, "tag", Tag)
    side = (
        "to_account"
        if account and account.kind == Account.Kind.EXPENSE
        else "from_account"
    )
    first: dict[str, Any] = {side: account.pk} if account else {}
    if tag:
        first["tags"] = [tag.pk]
    return _save_transaction_forms(
        request, Transaction(party=party), [first] if first else None
    )


def _from_query[M: (Account, Party, Tag)](
    request: HttpRequest, name: str, model: type[M]
) -> M | None:
    raw = request.GET.get(name, "")
    return model.objects.filter(pk=raw).first() if raw.isdecimal() else None


@db_transaction.non_atomic_requests
@login_required
@blocked_in_privacy_mode
def transaction_edit(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Edit a Transaction and its Splits."""
    # Listed, so the delete dialog has the total like the list's does.
    transaction = get_object_or_404(_listed_transactions(), pk=pk)
    if refused := _refused_as_investment(request, transaction):
        return refused
    return _save_transaction_forms(request, transaction)


def _refused_as_investment(
    request: HttpRequest, transaction: Transaction
) -> HttpResponseBase | None:
    """Send an Investment Event's Transaction to its Holdings, where it is changed.

    Editing it here would leave the event and its Transaction disagreeing.
    """
    event = getattr(transaction, "investment_event", None)
    if event is None:
        return None
    messages.error(
        request,
        f"This Transaction is the {event.get_kind_display()} of "
        f"{event.instrument}; change it on {event.account}'s Holdings.",
    )
    return redirect("account_holdings", pk=event.account_id)


@login_required
def split_row(request: HttpRequest) -> HttpResponse:
    """A blank Split row for the form's "add split" control."""
    return blank_split_row(request, SplitFormSet)


@login_required
@blocked_in_privacy_mode
def attachment_open(request: HttpRequest, pk: int) -> HttpResponseBase:  # noqa: ARG001
    """Send the browser to a short-lived storage link for the Attachment."""
    return redirect(get_object_or_404(Attachment, pk=pk).presigned_url())


@login_required
def transaction_delete(request: HttpRequest, pk: int) -> HttpResponseBase:
    """Confirm, then delete a Transaction, its Splits and its Attachments."""
    transaction = get_object_or_404(_listed_transactions(), pk=pk)
    if refused := _refused_as_investment(request, transaction):
        return refused
    if request.method == "POST":
        transaction.delete()
        return redirect(_return_url(request))
    return render(
        request,
        "transactions/transaction_confirm_delete.html",
        {"transaction": transaction, "return_url": _return_url(request)},
    )


@login_required
def storage(request: HttpRequest) -> HttpResponse:
    """Attachment storage figures from Velora's own records."""
    return render(
        request,
        "transactions/storage.html",
        {
            "stats": attachment_storage_stats(),
            "analytics": cloudflare.is_configured(),
        },
    )


def _from_outside[T](fetch: Callable[[], T], what: str) -> T | None:
    """Fetch figures from R2 or Cloudflare, or None when that fails."""
    try:
        return fetch()
    # Any failure, from missing credentials to a network error or a reply of
    # the wrong shape, only means these figures can't be shown; the rest of the
    # Storage page is unaffected.
    except Exception:
        logger.exception("Couldn't fetch %s.", what)
        return None


@login_required
def storage_analytics(request: HttpRequest) -> HttpResponse:
    """The Storage page's Cloudflare analytics section, loaded by htmx."""
    if not cloudflare.is_configured():
        raise Http404
    return render(
        request,
        "transactions/_storage_analytics.html",
        {
            "chart": _from_outside(
                lambda: storage_chart(cloudflare.daily_storage()),
                "Cloudflare storage analytics",
            ),
            "operations": _from_outside(
                lambda: count_operations(cloudflare.monthly_operations()),
                "Cloudflare operations analytics",
            ),
        },
    )


@login_required
def storage_bucket(request: HttpRequest) -> HttpResponse:
    """What the R2 bucket actually holds, loaded by the Storage page."""
    return render(
        request,
        "transactions/_storage_bucket.html",
        {"bucket": _from_outside(bucket_stats, "the R2 bucket listing")},
    )
