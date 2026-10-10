"""Proposing each Card EMI's interest, GST and fees as Drafts."""

from typing import TYPE_CHECKING

from django.db import transaction as db_transaction

from apps.cards.models import CardEMI
from apps.core.jobs import run_each
from apps.quick_add.models import Draft, DraftSplit

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal


@db_transaction.atomic
def propose_installment(emi: CardEMI, index: int) -> None:
    """Propose the interest and GST billed with the installment, and any fee.

    Nothing is proposed when nothing is charged, as for a no-cost EMI.
    """
    installment = emi.installments()[index]
    amounts: list[Decimal] = [installment.interest + installment.gst]
    if index == 0:
        amounts.append(emi.processing_fee)
    amounts = [amount for amount in amounts if amount > 0]
    if not amounts:
        return
    draft = Draft.objects.create(
        source=Draft.Source.CARD_EMI,
        card_emi=emi,
        installment=index + 1,
        date=emi.closing(index),
        description=f"{emi.card} Card EMI {index + 1} of {emi.months}",
    )
    for amount in amounts:
        DraftSplit.objects.create(
            draft=draft,
            from_account=emi.card,
            to_account=emi.interest_account,
            amount=amount,
        )


def propose_card_emi_drafts(today: date) -> None:
    """Propose every installment billed by today that has no Draft yet."""

    def propose_billed(emi: CardEMI) -> None:
        proposed = set(emi.drafts.values_list("installment", flat=True))
        for index in range(emi.billed_count):
            if emi.closing(index) <= today and index + 1 not in proposed:
                propose_installment(emi, index)

    run_each(
        "propose_card_emi_drafts",
        CardEMI.objects.select_related("card", "interest_account"),
        propose_billed,
    )
