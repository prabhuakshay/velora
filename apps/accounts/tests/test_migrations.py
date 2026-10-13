from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.tests.conftest import make_account
from apps.quick_add.tests.test_migrations import migrate

BEFORE = [("accounts", "0005_low_balance_threshold")]
AFTER = [("accounts", "0006_reconciliation")]


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_existing_accounts_take_one_reconciliation_per_day() -> None:
    migrate(BEFORE)
    bank = make_account("Bank", "asset").pk

    new = migrate(AFTER).loader.project_state(AFTER).apps
    reconciliations = new.get_model("accounts", "Reconciliation").objects
    day = {"account_id": bank, "date": date(2026, 3, 3)}
    reconciliations.create(**day, balance=Decimal(100))

    with pytest.raises(IntegrityError), transaction.atomic():
        reconciliations.create(**day, balance=Decimal(200))
    assert reconciliations.count() == 1
