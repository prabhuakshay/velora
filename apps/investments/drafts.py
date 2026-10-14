"""Drafts that carry a Buy, Sell or Dividend (ADR 0006, ADR 0012).

A Draft from an Investment Import or a SIP keeps its details with
`save_investment` and is posted with `apps.quick_add.posting.post_draft`,
like any Draft: posting records its Transaction and the linked Investment
Event together, through `apps.investments.events`.
"""

from typing import TYPE_CHECKING

from apps.investments.dividends import income_account
from apps.investments.ledger import route

if TYPE_CHECKING:
    from apps.accounts.models import Account
    from apps.investments.models import DraftInvestment


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
