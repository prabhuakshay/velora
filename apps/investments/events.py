"""Checking, recording and deleting Investment Events, on every path in.

An event comes in by hand, from an Investment Import, or as a posted Draft
(ADR 0006, ADR 0012). Whichever way, no Sell may take more units than held:
a recorded event is checked against the recorded events, and an event about
to become a Draft against them and the other waiting Drafts too, since an
import may draft a Buy that a later row's Sell draws on. A recorded event
moves its money through its own Transaction, kept in step with it, unless it
is new and already has one: an import's matched Transaction or a posted
Draft's. Recording any event queues a backfill of the Prices it may need.
"""

from typing import TYPE_CHECKING, cast

from django.utils import timezone

from apps.investments.dividends import linking, save_unlinked
from apps.investments.drafts import save_investment
from apps.investments.ledger import description, moves_ledger_money, transaction_forms
from apps.investments.models import NEEDS, DraftInvestment, InvestmentEvent
from apps.investments.replay import OversoldError, replay
from apps.investments.tasks import queue_backfill
from apps.quick_add.models import Draft
from apps.users.templatetags.amounts import plain_number

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.transactions.models import Transaction

PART_LABELS = {"units": "units", "amount": "the amount"}


def check(
    event: InvestmentEvent, income: Account | None = None, *, as_draft: bool = False
) -> list[str]:
    """Why the event, replacing its recorded self if any, can't be; empty if it can.

    A Dividend's Transaction comes from the given Income Account. As a Draft,
    its money is left to the Draft, so only its units are checked.
    """
    if refusal := _oversold(
        event.account, adding=event, leaving_out=event.pk, with_drafts=as_draft
    ):
        return [refusal]
    if as_draft or _keeps_its_transaction(event):
        return []
    money = transaction_forms(event, income)
    return [] if money is None or money.is_valid() else money.errors()


def record(event: InvestmentEvent, income: Account | None = None) -> None:
    """Save the checked event with the money it moves, and queue a backfill."""
    if _keeps_its_transaction(event):
        event.save()
    elif (money := transaction_forms(event, income)) is None:
        save_unlinked(event)
    elif money.is_valid():
        money.save(within=linking(event, money))
    else:
        message = f"Check the event before recording it: {' '.join(money.errors())}"
        raise ValueError(message)
    queue_backfill()


def delete(event: InvestmentEvent) -> str:
    """Delete the event and its Transaction; why not, if a Sell needs its units."""
    if refusal := _oversold(event.account, leaving_out=event.pk):
        return refusal
    event.delete()
    if event.transaction is not None:
        event.transaction.delete()
    return ""


def propose(event: InvestmentEvent, source: Draft.Source) -> Draft:
    """Save the checked event as a waiting Draft carrying it, to post once reviewed."""
    draft = Draft.objects.create(
        source=source, date=event.date, description=description(event)
    )
    save_investment(DraftInvestment.carrying(event, draft))
    return draft


def draft_problems(draft: Draft) -> list[str]:
    """Why the Draft's Investment Event can't be recorded yet; empty when it can."""
    detail: DraftInvestment | None = getattr(draft, "investment", None)
    if detail is None:
        return []
    if missing := [
        f"Missing {PART_LABELS[name]}."
        for name in NEEDS[detail.kind]
        if name in PART_LABELS and getattr(detail, name) is None
    ]:
        return missing
    event = detail.event_on(min(draft.date, timezone.localdate()))
    if not moves_ledger_money(event):
        return [
            (
                f"It is dated on or before {event.account}'s Opening Balance date; "
                "record it on its Holdings tab instead."
            )
        ]
    refusal = _oversold(event.account, adding=event)
    return [refusal] if refusal else []


def draft_posted(draft: Draft, transaction: Transaction) -> None:
    """Record the Investment Event the posted Draft carries, linked to its money."""
    detail: DraftInvestment | None = getattr(draft, "investment", None)
    if detail is not None:
        event = detail.event_on(transaction.date)
        event.transaction = transaction
        record(event)


def _keeps_its_transaction(event: InvestmentEvent) -> bool:
    return not event.pk and event.transaction is not None


def _oversold(
    account: Account,
    *,
    adding: InvestmentEvent | None = None,
    leaving_out: int | None = None,
    with_drafts: bool = False,
) -> str:
    recorded = account.investment_events.select_related("instrument")
    if leaving_out is not None:
        recorded = recorded.exclude(pk=leaving_out)
    events = list(recorded)
    if with_drafts:
        events += [
            detail.event_on(detail.draft.date)
            for detail in account.investment_drafts.filter(
                draft__status=Draft.Status.WAITING, units__isnull=False
            ).select_related("draft", "instrument")
        ]
    if adding is not None:
        events.append(adding)
    try:
        replay(events)
    except OversoldError as error:
        sold = cast("InvestmentEvent", error.event)
        return (
            f"Only {plain_number(error.held)} units of {sold.instrument} were held "
            f"on {sold.date:%-d %b %Y}."
        )
    return ""
