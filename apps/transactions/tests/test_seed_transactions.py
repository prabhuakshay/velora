import pytest
from django.core.management import call_command

from apps.accounts.models import Account, AccountKind
from apps.accounts.tests.conftest import make_account
from apps.classification.models import Party
from apps.transactions.models import Transaction

pytestmark = pytest.mark.django_db


def test_seed_keeps_every_balance_and_net_worth_positive() -> None:
    call_command("seed_transactions", months=2, per_month=50)

    assert Transaction.objects.count() == 100
    balances = Account.objects.with_balance().filter(kind=AccountKind.ASSET)
    assert all(account.balance > 0 for account in balances)
    card = Account.objects.with_balance().get(kind=AccountKind.LIABILITY)
    assert card.balance == 0


def test_reset_replaces_existing_data() -> None:
    make_account("Old Bank", AccountKind.ASSET)
    Party.objects.create(name="Old Party")

    call_command("seed_transactions", months=1, per_month=10, reset=True)
    call_command("seed_transactions", months=1, per_month=10, reset=True)

    assert not Account.objects.filter(name="Old Bank").exists()
    assert not Party.objects.filter(name="Old Party").exists()
    assert Transaction.objects.count() == 10
