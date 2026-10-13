"""Drafts that carry a Buy, Sell or Dividend (ADR 0006, ADR 0012).

A Draft from an Investment Import or a SIP is made with `save_investment`
and posted with `apps.quick_add.posting.post_draft`, like any Draft: posting
records its Transaction and the linked Investment Event together.
"""

from typing import TYPE_CHECKING

from django.utils import timezone

from apps.investments.dividends import income_account
from apps.investments.ledger import moves_ledger_money, route
from apps.investments.models import NEEDS
from apps.investments.overselling import oversell_refusal
from apps.investments.replay import BUY

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.investments.models import DraftInvestment, InvestmentEvent
    from apps.quick_add.models import Draft

PART_LABELS = {"units": "units", "price": "the Price", "amount": "the amount"}


def save_investment(detail: DraftInvestment, income: Account | None = None) -> None:
    """Save the Draft's investment details and rewrite its one Split to match.

    The Split is what the Draft shows and posts, routed by the ledger rules.
    A Dividend keeps the Income Account its Split has unless given another.
    """
    draft = detail.draft
    income = income or income_account(draft)
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
        f"Missing {PART_LABELS[name]}."
        for name in NEEDS[detail.kind]
        if name in PART_LABELS and getattr(detail, name) is None
    ]:
        return missing
    refusal = _refusal(detail.event_on(min(draft.date, timezone.localdate())))
    return [refusal] if refusal else []


def _refusal(event: InvestmentEvent) -> str:
    """Why the complete event can't be recorded; empty when it can."""
    if not moves_ledger_money(event):
        return (
            f"It is dated on or before {event.account}'s Opening Balance date; "
            "record it on its Holdings tab instead."
        )
    return oversell_refusal(event.account, adding=event)
