"""Drafts that carry a Buy, Sell or Dividend (ADR 0006, ADR 0012).

A Draft from an Investment Import or a SIP is made with `save_investment`
and posted with `apps.quick_add.posting.post_draft`, like any Draft: posting
records its Transaction and the linked Investment Event together.
"""

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.investments.forms import oversold_message
from apps.investments.ledger import moves_money, route
from apps.investments.replay import BUY, DIVIDEND, SELL, OversoldError, replay

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.investments.models import DraftInvestment, InvestmentEvent
    from apps.quick_add.models import Draft

TRADE_PARTS = (("units", "units"), ("price", "the Price"), ("amount", "the amount"))
NEEDS = {BUY: TRADE_PARTS, SELL: TRADE_PARTS, DIVIDEND: TRADE_PARTS[2:]}


def income_of(draft: Draft) -> Account | None:
    """The From of the Draft's Split: a Dividend's Income Account."""
    split = draft.splits.select_related("from_account").first()
    return None if split is None else split.from_account


def save_investment(detail: DraftInvestment, income: Account | None = None) -> None:
    """Save the Draft's investment details and rewrite its one Split to match.

    The Split is what the Draft shows and posts, routed by the ledger rules.
    A Dividend keeps the Income Account its Split has unless given another.
    """
    draft = detail.draft
    income = income or income_of(draft)
    detail.save()
    source, destination, amount = route(detail.event_on(draft.date), income)
    draft.splits.all().delete()
    draft.splits.create(
        from_account_id=source, to_account_id=destination, amount=amount
    )


def buys_units(draft: Draft) -> bool:
    """Whether the Draft carries a Buy, which may need past Prices backfilled."""
    detail: DraftInvestment | None = getattr(draft, "investment", None)
    return detail is not None and detail.kind == BUY


def investment_problems(draft: Draft) -> list[str]:
    """Why the Draft's Investment Event can't be recorded yet; empty when it can."""
    detail: DraftInvestment | None = getattr(draft, "investment", None)
    if detail is None:
        return []
    if missing := [
        f"Missing {label}."
        for name, label in NEEDS[detail.kind]
        if getattr(detail, name) is None
    ]:
        return missing
    refusal = _refusal(detail.event_on(min(draft.date, timezone.localdate())))
    return [refusal] if refusal else []


def _refusal(event: InvestmentEvent) -> str:
    """Why the complete event can't be recorded; empty when it can."""
    if not moves_money(event):
        return (
            f"It is dated on or before {event.account}'s Opening Balance date; "
            "record it on its Holdings tab instead."
        )
    others = event.account.investment_events.select_related("instrument")
    try:
        replay([*others, event])
    except OversoldError as error:
        return oversold_message(error)
    return ""
