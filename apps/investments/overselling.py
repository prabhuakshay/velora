"""Refusing a change that would leave a Sell taking more units than held."""

from typing import TYPE_CHECKING, cast

from apps.investments.replay import OversoldError, replay
from apps.quick_add.models import Draft
from apps.users.templatetags.amounts import plain_number

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.investments.models import InvestmentEvent


def oversold_message(error: OversoldError) -> str:
    """Why a Sell can't take the units it asks for."""
    event = cast("InvestmentEvent", error.event)
    return (
        f"Only {plain_number(error.held)} units of {event.instrument} were held "
        f"on {event.date:%-d %b %Y}."
    )


def oversell_refusal(
    account: Account,
    *,
    adding: InvestmentEvent | None = None,
    leaving_out: int | None = None,
    with_drafts: bool = False,
) -> str:
    """Why the account's events would sell units not held; empty when they wouldn't.

    That is its events with adding and without the one leaving_out, and, with
    drafts, the Buys and Sells its waiting Drafts will record once posted.
    """
    recorded = account.investment_events.select_related("instrument")
    if leaving_out is not None:
        recorded = recorded.exclude(pk=leaving_out)
    events = list(recorded)
    if with_drafts:
        events += _waiting_drafts(account)
    if adding is not None:
        events.append(adding)
    try:
        replay(events)
    except OversoldError as error:
        return oversold_message(error)
    return ""


def _waiting_drafts(account: Account) -> list[InvestmentEvent]:
    return [
        detail.event_on(detail.draft.date)
        for detail in account.investment_drafts.filter(
            draft__status=Draft.Status.WAITING, units__isnull=False
        ).select_related("draft", "instrument")
    ]
