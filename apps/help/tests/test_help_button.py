from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card, make_card_emi, record
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def _help_link(client: Client, url: str) -> str:
    body = client.get(url).content.decode()
    assert 'popovertarget="help-menu"' in body
    menu = body.split('id="help-menu"', 1)[1].split("</div>", 1)[0]
    return menu.split('href="', 1)[1].split('"', 1)[0]


@pytest.mark.parametrize(
    ("url_name", "args", "area"),
    [
        ("index", [], None),
        ("transaction_list", [], "transactions"),
        ("draft_list", [], "drafts"),
        ("schedule_list", [], "schedules"),
        ("subscription_list", [], "schedules"),
        ("forecast", [], "forecast"),
        ("budget_list", [], "budgets"),
        ("account_list", ["asset"], "accounts"),
        ("account_list", ["liability"], "accounts"),
        ("investments_overview", [], "investments"),
        ("goal_list", [], "goals"),
        ("party_list", [], "classification"),
        ("tag_list", [], "classification"),
    ],
)
def test_every_main_page_links_to_its_help(
    signed_in: Client, url_name: str, args: list[str], area: str | None
) -> None:
    expected = reverse("help_area", args=[area]) if area else reverse("help_index")

    assert _help_link(signed_in, reverse(url_name, args=args)) == expected


def test_a_credit_card_links_to_cards_help(signed_in: Client) -> None:
    card = make_card()
    url = reverse("account_transactions", args=["liability", card.pk])

    assert _help_link(signed_in, url) == reverse("help_area", args=["cards"])


def test_statement_pages_link_to_cards_help(signed_in: Client) -> None:
    card = make_card()
    record(card, make_account("Groceries", "expense"), "1200", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    billed = Statement.objects.get()
    cards_help = reverse("help_area", args=["cards"])

    assert _help_link(signed_in, reverse("statement_edit", args=[billed.pk])) == (
        cards_help
    )
    history = reverse("statement_history", args=["liability", card.pk])
    assert _help_link(signed_in, history) == cards_help


def test_a_card_emi_links_to_cards_help(signed_in: Client) -> None:
    emi = make_card_emi(make_card())
    url = reverse("card_emi_detail", args=[emi.pk])

    assert _help_link(signed_in, url) == reverse("help_area", args=["cards"])
