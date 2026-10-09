from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.transactions.models import Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def record(party: Party | None) -> Transaction:
    count = Transaction.objects.count()
    bank = make_account(f"Bank {count}", "asset")
    groceries = make_account(f"Groceries {count}", "expense")
    transaction = Transaction.objects.create(date=date(2026, 3, 1), party=party)
    transaction.splits.create(
        from_account=bank, to_account=groceries, amount=Decimal(5)
    )
    return transaction


def merge_url(party: Party) -> str:
    return reverse("party_merge", args=[party.pk])


def test_every_party_row_links_to_merge(signed_in: Client) -> None:
    parties = [
        Party.objects.create(name="Big Bazar"),
        Party.objects.create(name="Old shop", hidden=True),
    ]

    body = signed_in.get(reverse("party_list") + "?show_hidden=1").content.decode()

    for party in parties:
        assert f'href="{merge_url(party)}"' in body


def test_merge_page_shows_transaction_count_and_other_parties(
    signed_in: Client,
) -> None:
    source = Party.objects.create(name="Big Bazar")
    Party.objects.create(name="Big Bazaar")
    record(source)
    record(source)

    body = signed_in.get(merge_url(source)).content.decode()

    assert "2 Transactions" in body
    assert ">Big Bazaar</option>" in body
    assert ">Big Bazar</option>" not in body


def test_merge_points_transactions_at_target_and_removes_source(
    signed_in: Client, user: User
) -> None:
    source = Party.objects.create(name="Big Bazar")
    target = Party.objects.create(name="Big Bazaar")
    moved = [record(source), record(source)]
    untouched = record(None)

    response = signed_in.post(merge_url(source), {"target": target.pk}, follow=True)

    assert response.redirect_chain == [(reverse("party_list"), 302)]
    assert "Merged Big Bazar into Big Bazaar." in response.content.decode()
    assert list(Party.objects.all()) == [target]
    assert set(target.transactions.all()) == set(moved)
    untouched.refresh_from_db()
    assert untouched.party is None
    reason = "Merged Big Bazar into Big Bazaar"
    deleted = Party.history.get(id=source.pk, history_type="-")
    assert (deleted.history_user, deleted.history_change_reason) == (user, reason)
    for transaction in moved:
        latest = transaction.history.latest()
        assert (latest.party_id, latest.history_user, latest.history_change_reason) == (
            target.pk,
            user,
            reason,
        )


def test_merge_into_itself_is_rejected(signed_in: Client) -> None:
    source = Party.objects.create(name="Big Bazar")
    transaction = record(source)

    response = signed_in.post(merge_url(source), {"target": source.pk})

    assert response.status_code == 200
    assert "Select a valid choice." in response.content.decode()
    transaction.refresh_from_db()
    assert transaction.party == source
    assert Party.objects.get() == source


@pytest.mark.parametrize("method", ["get", "post"])
def test_deleting_party_in_use_redirects_to_merge_mentioning_hide(
    signed_in: Client, method: str
) -> None:
    party = Party.objects.create(name="Big Bazar")
    record(party)
    url = reverse("party_delete", args=[party.pk])

    response = getattr(signed_in, method)(url, follow=True)

    assert response.redirect_chain == [(merge_url(party), 302)]
    body = response.content.decode()
    assert "used by Transactions" in body
    assert "hide" in body
    assert Party.objects.get() == party
