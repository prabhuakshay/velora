from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.tests.conftest import make_account
from apps.quick_add.tests.test_migrations import migrate

BEFORE = [("cards", "0002_card_emi")]
AFTER = [("cards", "0004_statement_payments")]


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_each_statement_keeps_the_payment_it_was_paid_by() -> None:
    old = migrate(BEFORE).loader.project_state(BEFORE).apps
    Statement = old.get_model("cards", "Statement")
    Transaction = old.get_model("transactions", "Transaction")
    # Only the cards app moved back, so the Account is made as it is now.
    card = make_account("HDFC card", "liability").pk
    payment = Transaction.objects.create(date=date(2026, 11, 3))
    other = Transaction.objects.create(date=date(2026, 11, 4))
    period = {"period_start": date(2026, 9, 16), "estimated_amount": Decimal(1200)}
    paid = Statement.objects.create(
        card_id=card,
        period_end=date(2026, 10, 15),
        due_date=date(2026, 11, 5),
        transaction=payment,
        **period,
    )
    Statement.objects.create(
        card_id=card,
        period_end=date(2026, 11, 15),
        due_date=date(2026, 12, 5),
        **period,
    )

    new = migrate(AFTER).loader.project_state(AFTER).apps
    transactions = new.get_model("transactions", "Transaction").objects

    assert transactions.get(pk=payment.pk).statement_id == paid.pk
    assert transactions.get(pk=other.pk).statement_id is None
