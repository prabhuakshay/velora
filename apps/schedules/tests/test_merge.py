from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.models import Account
from apps.accounts.tests.conftest import account_url, make_account
from apps.classification.models import Party
from apps.schedules.models import Occurrence, ScheduleSplit, SuggestedSchedule
from apps.schedules.occurrences import materialise_occurrences
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


def test_a_schedule_left_with_no_splits_is_paused_not_deleted(
    signed_in: Client,
) -> None:
    old_bank = make_account("Old bank", "asset")
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    emptied = make_schedule((bank, old_bank, "500"))
    kept = make_schedule((bank, old_bank, "500"), (bank, rent, "10"))
    materialise_occurrences(date(2026, 10, 1))

    signed_in.post(account_url("account_merge", old_bank), {"target": bank.pk})

    emptied.refresh_from_db()
    kept.refresh_from_db()
    assert (emptied.active, emptied.splits.count()) == (False, 0)
    assert not emptied.occurrences.filter(status=Occurrence.Status.UPCOMING).exists()
    assert (kept.active, kept.splits.count()) == (True, 1)


def test_merging_a_party_moves_its_schedules(signed_in: Client) -> None:
    old = Party.objects.create(name="Old landlord")
    landlord = Party.objects.create(name="Landlord")
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    schedule = make_schedule((bank, rent, "25000"), party=old)

    response = signed_in.post(
        reverse("party_merge", args=[old.pk]), {"target": landlord.pk}
    )

    assert response.status_code == 302
    schedule.refresh_from_db()
    assert schedule.party == landlord
    assert not Party.objects.filter(pk=old.pk).exists()


def test_party_merge_page_counts_schedules(signed_in: Client) -> None:
    old = Party.objects.create(name="Old landlord")
    Party.objects.create(name="Landlord")
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    make_schedule((bank, rent, "1"), party=old)
    make_schedule((bank, rent, "2"), party=old)

    body = signed_in.get(reverse("party_merge", args=[old.pk])).content.decode()

    assert "2 Schedules" in body


@pytest.mark.parametrize("method", ["get", "post"])
def test_deleting_a_party_with_only_a_schedule_redirects_to_merge(
    signed_in: Client, method: str
) -> None:
    party = Party.objects.create(name="Landlord")
    bank = make_account("Bank", "asset")
    rent = make_account("Rent", "expense")
    make_schedule((bank, rent, "1"), party=party)

    response = getattr(signed_in, method)(reverse("party_delete", args=[party.pk]))

    assert response["Location"] == reverse("party_merge", args=[party.pk])
    assert Party.objects.filter(pk=party.pk).exists()


def _suggest(party: Party, source: Account, destination: Account) -> None:
    SuggestedSchedule.objects.create(
        party=party,
        from_account=source,
        to_account=destination,
        amount=Decimal(10),
        unit="month",
    )


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    "use", ["split_from", "split_to", "suggested_from", "suggested_to"]
)
def test_deleting_an_account_used_only_by_a_schedule_redirects_to_merge(
    signed_in: Client, method: str, use: str
) -> None:
    used = make_account("Used", "asset")
    other = make_account("Other", "expense")
    party = Party.objects.create(name="Landlord")
    pair = (used, other) if use.endswith("from") else (other, used)
    if use.startswith("split"):
        make_schedule((*pair, "1"))
    else:
        _suggest(party, *pair)

    response = getattr(signed_in, method)(account_url("account_delete", used))

    assert response["Location"] == account_url("account_merge", used)
    assert Account.objects.filter(pk=used.pk).exists()
