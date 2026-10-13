"""SIPs: Schedules whose Drafts buy one Instrument (ADR 0007, ADR 0012).

A SIP's Draft is a Buy whose units come from the Price on its due date, or
the next Price published. Until there is one it waits with its units open,
and the daily job fills them in once a Price arrives.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.jobs import run_each
from apps.investments.drafts import save_investment
from apps.investments.models import DraftInvestment, Price
from apps.investments.replay import BUY
from apps.quick_add.models import Draft
from apps.quick_add.posting import try_posting

if TYPE_CHECKING:
    from datetime import date

    from apps.schedules.models import Schedule

UNIT = Decimal("0.000001")


def draft_sip_buy(draft: Draft, schedule: Schedule) -> None:
    """Make the Schedule's Draft a Buy, priced if its Price is out yet."""
    detail = DraftInvestment(
        draft=draft,
        account=schedule.sip_account,
        instrument=schedule.sip_instrument,
        kind=BUY,
        amount=draft.amount,
    )
    _price(detail)
    save_investment(detail)


def fill_sip_units(today: date) -> None:
    """Fill in the units of every waiting SIP Draft whose Price is now out.

    An auto-post SIP still within grace is posted, as on its due date.
    """
    waiting = DraftInvestment.objects.filter(
        draft__status=Draft.Status.WAITING,
        draft__occurrence__schedule__sip_account__isnull=False,
        kind=BUY,
        units__isnull=True,
        price__isnull=True,
        amount__isnull=False,
    ).select_related("draft__occurrence__schedule", "account", "instrument")
    run_each("fill_sip_units", waiting, lambda detail: _fill(detail, today))


def _fill(detail: DraftInvestment, today: date) -> None:
    if not _price(detail):
        return
    save_investment(detail)
    draft = detail.draft
    draft.posting_error = ""
    draft.save(update_fields=["posting_error"])
    occurrence = draft.occurrence
    if occurrence is not None and occurrence.auto_posts_on(today):
        try_posting(draft)


def _price(detail: DraftInvestment) -> bool:
    """Set the units the amount buys at the first Price from the due date on."""
    price = (
        Price.objects.filter(instrument=detail.instrument, date__gte=detail.draft.date)
        .order_by("date")
        .first()
    )
    if price is None or detail.amount is None:
        return False
    detail.price = price.price
    detail.units = (detail.amount / price.price).quantize(UNIT)
    return True
