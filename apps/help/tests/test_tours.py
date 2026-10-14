import html
import re
from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.cards.models import Statement
from apps.cards.tests.conftest import make_card, record
from apps.goals.tests.conftest import create_goal
from apps.help.tests.conftest import avoided_terms_in
from apps.investments.tests.conftest import make_broker
from apps.schedules.daily_job import run_daily_job

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

STEP = re.compile(r'data-tour-step="(\d+)" data-tour-text="([^"]+)"')


def _tour(client: Client, url: str) -> tuple[str, str, list[tuple[int, str]]]:
    """The page's tour id, its Help link and its steps, in step order."""
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    menu = body.split('id="help-menu"', 1)[1].split(">", 1)[0]
    tour = re.search(r'data-tour="([^"]+)"', menu)
    help_url = re.search(r'data-tour-help="([^"]+)"', menu)
    assert tour
    assert help_url
    assert "data-tour-start" in body
    steps = sorted((int(n), html.unescape(text)) for n, text in STEP.findall(body))
    return tour[1], help_url[1], steps


def _assert_tour(client: Client, url: str, tour: str, area: str | None) -> None:
    found, help_url, steps = _tour(client, url)

    assert found == tour
    expected = reverse("help_area", args=[area]) if area else reverse("help_index")
    assert help_url == expected
    # Steps sharing a number are one step, shown at different widths.
    assert 3 <= len({n for n, _ in steps}) <= 6
    for _, text in steps:
        assert avoided_terms_in(text) == set(), text


@pytest.mark.parametrize(
    ("url_name", "args", "tour", "area"),
    [
        ("index", [], "home", None),
        ("transaction_list", [], "transactions", "transactions"),
        ("draft_list", [], "drafts", "drafts"),
        ("schedule_list", [], "schedules", "schedules"),
        ("subscription_list", [], "subscriptions", "schedules"),
        ("forecast", [], "forecast", "forecast"),
        ("budget_list", [], "budgets", "budgets"),
        ("account_list", ["asset"], "accounts", "accounts"),
        ("investments_overview", [], "investments", "investments"),
        ("goal_list", [], "goals", "goals"),
        ("party_list", [], "parties", "classification"),
        ("tag_list", [], "tags", "classification"),
        ("transaction_create", [], "transaction-form", "transactions"),
        ("investment_import", [], "investment-import", "investments"),
    ],
)
def test_main_page_has_a_tour(
    signed_in: Client, url_name: str, args: list[str], tour: str, area: str | None
) -> None:
    _assert_tour(signed_in, reverse(url_name, args=args), tour, area)


def test_an_account_has_a_tour(signed_in: Client) -> None:
    bank = make_account("HDFC", "asset")
    url = reverse("account_transactions", args=["asset", bank.pk])

    _assert_tour(signed_in, url, "account", "accounts")


def test_reconcile_has_a_tour(signed_in: Client) -> None:
    bank = make_account("HDFC", "asset")
    url = reverse("account_reconcile", args=["asset", bank.pk])

    _assert_tour(signed_in, url, "reconcile", "accounts")


def test_a_credit_card_has_its_own_tour(signed_in: Client) -> None:
    card = make_card()
    url = reverse("account_transactions", args=["liability", card.pk])

    _assert_tour(signed_in, url, "card", "cards")


def test_a_statement_has_a_tour(signed_in: Client) -> None:
    card = make_card()
    record(card, make_account("Groceries", "expense"), "1200", date(2026, 9, 20))
    run_daily_job(date(2026, 10, 16))
    url = reverse("statement_edit", args=[Statement.objects.get().pk])

    _assert_tour(signed_in, url, "statement", "cards")


def test_an_investment_account_has_its_own_tour(signed_in: Client) -> None:
    broker = make_broker()
    url = reverse("account_transactions", args=["asset", broker.pk])

    _assert_tour(signed_in, url, "investment-account", "investments")


def test_holdings_have_a_tour(signed_in: Client) -> None:
    url = reverse("account_holdings", args=[make_broker().pk])

    _assert_tour(signed_in, url, "holdings", "investments")


def test_a_goal_has_a_tour(signed_in: Client) -> None:
    goal = create_goal(signed_in)
    assert goal

    _assert_tour(signed_in, reverse("goal_detail", args=[goal.pk]), "goal", "goals")


def test_a_page_without_a_tour_offers_none(signed_in: Client) -> None:
    card = make_card()
    body = signed_in.get(
        reverse("statement_history", args=["liability", card.pk])
    ).content.decode()

    assert 'popovertarget="help-menu"' in body
    assert "data-tour-start" not in body
    assert "data-tour-step" not in body


def test_every_page_loads_the_tour_engine(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "js/driver.js" in body
    assert "js/tour.js" in body
