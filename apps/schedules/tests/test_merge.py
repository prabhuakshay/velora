from typing import TYPE_CHECKING

import pytest

from apps.accounts.tests.conftest import account_url, make_account
from apps.schedules.models import ScheduleSplit
from apps.schedules.tests.conftest import make_schedule

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_merging_an_account_repoints_schedule_splits(signed_in: Client) -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    schedule = make_schedule((old_bank, rent, "25000"))
    transfer = make_schedule((bank, old_bank, "500"), (rent, old_bank, "10"))

    signed_in.post(account_url("account_merge", old_bank), {"target": bank.pk})

    assert [
        (split.from_account, split.to_account) for split in schedule.splits.all()
    ] == [(bank, rent)]
    # Bank to Bank moves nothing, as with a Transaction's self-Split.
    assert [
        (split.from_account, split.to_account) for split in transfer.splits.all()
    ] == [(rent, bank)]
    assert ScheduleSplit.history.filter(
        history_change_reason="Merged Old bank into Bank"
    ).exists()
