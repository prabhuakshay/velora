from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.urls import reverse

from apps.accounts.models import Account

if TYPE_CHECKING:
    from django.test import Client

KINDS = ["asset", "liability", "expense", "income"]


def list_url(kind: str) -> str:
    return reverse("account_list", kwargs={"kind": kind})


def list_page(client: Client, kind: str) -> str:
    return client.get(list_url(kind)).content.decode()


def account_url(name: str, account: Account) -> str:
    return reverse(name, kwargs={"kind": account.kind, "pk": account.pk})


def make_account(name: str, kind: str, *, hidden: bool = False) -> Account:
    account = Account(name=name, kind=kind, hidden=hidden)
    if account.has_opening_balance:
        account.opening_balance = Decimal(0)
        account.opening_balance_date = date(2026, 1, 1)
    account.save()
    return account
