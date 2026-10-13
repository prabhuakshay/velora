from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.tests.conftest import account_url, make_account, page_text
from apps.cards.models import Statement

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


def bill(card: Account, months: range) -> None:
    """A Statement of 100 per month closing on the 15th of each month of 2026."""
    for month in months:
        Statement.objects.create(
            card=card,
            period_start=date(2026, month - 1, 16),
            period_end=date(2026, month, 15),
            due_date=date(2026, month + 1, 5),
            estimated_amount=Decimal(100 * month),
        )


def card_page(client: Client, card: Account) -> str:
    return page_text(
        client.get(account_url("account_transactions", card)).content.decode()
    )


def history_page(client: Client, card: Account) -> str:
    return page_text(
        client.get(account_url("statement_history", card)).content.decode()
    )


def test_card_page_lists_only_the_latest_five_statements(
    signed_in: Client, card: Account
) -> None:
    bill(card, range(2, 9))

    page = card_page(signed_in, card)

    assert (
        "Due 5 Sep 2026 16 Jul to 15 Aug 2026 ₹800.00 Estimate"
        " Due 5 Aug 2026 16 Jun to 15 Jul 2026 ₹700.00 Estimate"
        " Due 5 Jul 2026 16 May to 15 Jun 2026 ₹600.00 Estimate"
        " Due 5 Jun 2026 16 Apr to 15 May 2026 ₹500.00 Estimate"
        " Due 5 May 2026 16 Mar to 15 Apr 2026 ₹400.00 Estimate"
    ) in page
    assert "Due 5 Apr 2026" not in page
    assert "Show all 7" in page


def test_card_page_has_no_show_all_link_with_five_or_fewer(
    signed_in: Client, card: Account
) -> None:
    bill(card, range(2, 7))

    assert "Show all" not in card_page(signed_in, card)


def test_history_lists_every_statement_newest_first(
    signed_in: Client, card: Account
) -> None:
    bill(card, range(2, 9))

    page = history_page(signed_in, card)

    assert (
        "Due 5 Apr 2026 16 Feb to 15 Mar 2026 ₹300.00 Estimate"
        " Due 5 Mar 2026 16 Jan to 15 Feb 2026 ₹200.00 Estimate"
    ) in page
    assert page.index("Due 5 Sep 2026") < page.index("Due 5 Mar 2026")


def test_history_is_only_for_cards(signed_in: Client) -> None:
    loan = make_account("Loan", "liability")

    assert signed_in.get(account_url("statement_history", loan)).status_code == 404


def _queries_to_view(client: Client, card: Account) -> int:
    with CaptureQueriesContext(connection) as queries:
        card_page(client, card)
    return len(queries)


def test_card_page_query_count_does_not_grow_with_statements(
    signed_in: Client, card: Account
) -> None:
    bill(card, range(2, 3))
    few = _queries_to_view(signed_in, card)

    bill(card, range(3, 10))

    assert _queries_to_view(signed_in, card) == few
