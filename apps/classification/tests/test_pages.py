import re
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import make_account, page_text
from apps.classification.models import Party, Tag
from apps.classification.tests.conftest import move
from apps.schedules.models import Schedule
from apps.users.tests.conftest import turn_on

if TYPE_CHECKING:
    from django.test import Client

    from apps.accounts.models import Account

pytestmark = pytest.mark.django_db


@pytest.fixture
def bank() -> Account:
    return make_account("Bank", "asset")


@pytest.fixture
def food() -> Account:
    return make_account("Food", "expense")


def text(client: Client, name: str, *args: object, query: str = "") -> str:
    return page_text(client.get(reverse(name, args=args) + query).content.decode())


def test_tabs_count_visible_parties_and_tags(signed_in: Client) -> None:
    Party.objects.create(name="Shop")
    Party.objects.create(name="Old", hidden=True)
    Tag.objects.create(name="Trip")

    assert "Parties 1 Tags 1" in text(signed_in, "party_list")
    assert "Parties 1 Tags 1" in text(signed_in, "tag_list")


def test_party_list_shows_each_partys_year_and_the_totals(
    signed_in: Client, bank: Account, food: Account
) -> None:
    today = timezone.localdate()
    shop = Party.objects.create(name="Shop")
    Party.objects.create(name="Unused")
    move(today, bank, food, "250", party=shop)
    move(today - timedelta(days=400), bank, food, "999", party=shop)

    page = text(signed_in, "party_list")

    assert "Spent with Parties ₹250.00" in page
    assert "1 never used" in page
    assert f"Shop Spent ₹250.00 2 Transactions · last {today:%-d %b %Y}" in page
    assert "Unused No Transactions yet" in page


def test_party_list_sorts_by_amount_and_recent(
    signed_in: Client, bank: Account, food: Account
) -> None:
    today = timezone.localdate()
    big, small = Party.objects.create(name="Big"), Party.objects.create(name="Small")
    Party.objects.create(name="Aardvark")
    move(today - timedelta(days=5), bank, food, "900", party=big)
    move(today, bank, food, "10", party=small)

    by_amount = text(signed_in, "party_list", query="?sort=amount")
    recent = text(signed_in, "party_list", query="?sort=recent")

    assert by_amount.index("Big") < by_amount.index("Small") < by_amount.index("Aard")
    assert recent.index("Small") < recent.index("Big") < recent.index("Aardvark")


def test_party_page_sums_its_money_and_lists_its_schedules(
    signed_in: Client, bank: Account, food: Account
) -> None:
    today = timezone.localdate()
    shop = Party.objects.create(name="Shop", notes="Near home")
    move(today, bank, food, "120", party=shop, description="Groceries")
    Schedule.objects.create(party=shop, start_date=today, description="Weekly shop")

    page = text(signed_in, "party_transactions", shop.pk)

    assert "Spent · all time ₹120.00" in page
    assert "Spent on Food ₹120.00 100%" in page
    assert "Groceries ₹120.00 Bank → Food" in page
    assert "Schedules Weekly shop Active" in page
    assert "Near home" in page
    assert "while used by Transactions" in page


def test_unused_party_page_offers_delete_in_place(signed_in: Client) -> None:
    party = Party.objects.create(name="Shop")
    url = reverse("party_delete", args=[party.pk])

    page = signed_in.get(reverse("party_transactions", args=[party.pk]))
    response = signed_in.post(url)

    assert f'action="{url}"' in page.content.decode()
    assert response["Location"] == reverse("party_list")
    assert not Party.objects.exists()


def test_tag_list_counts_each_split_once(
    signed_in: Client, bank: Account, food: Account
) -> None:
    trip, work = Tag.objects.create(name="Trip"), Tag.objects.create(name="Work")
    move(timezone.localdate(), bank, food, "80", tags=[trip, work])

    page = text(signed_in, "tag_list")

    assert "Tagged spending ₹80.00" in page
    assert "Trip Spent ₹80.00 On 1 Split" in page


def test_tag_page_shows_the_tagged_part_of_each_transaction(
    signed_in: Client, bank: Account, food: Account
) -> None:
    trip = Tag.objects.create(name="Trip")
    cafe = Party.objects.create(name="Cafe")
    split = move(timezone.localdate(), bank, food, "60", party=cafe, tags=[trip])
    split.transaction.splits.create(
        from_account=bank, to_account=make_account("Gifts", "expense"), amount=40
    )

    page = text(signed_in, "tag_transactions", trip.pk)

    assert "Spent · all time ₹60.00" in page
    assert "Cafe ₹60.00 Bank → Food +1 of ₹100.00" in page
    assert "Parties Cafe ₹60.00 100%" in page
    assert "It comes off every Split" in page


def test_detail_pages_hide_the_chart_in_privacy_mode(signed_in: Client) -> None:
    party = Party.objects.create(name="Shop")
    tag = Tag.objects.create(name="Trip")
    turn_on(signed_in)

    for name, pk in [("party_transactions", party.pk), ("tag_transactions", tag.pk)]:
        body = signed_in.get(reverse(name, args=[pk])).content.decode()
        assert "Hidden in Privacy Mode" in body
        assert "<line x1=" not in body


def test_new_transaction_starts_with_the_party_and_tag(signed_in: Client) -> None:
    shop = Party.objects.create(name="Shop")
    trip = Tag.objects.create(name="Trip")

    body = signed_in.get(
        reverse("transaction_create"), {"party": shop.pk, "tag": trip.pk}
    ).content.decode()

    party = body.split('name="party"')[1].split("</select>")[0]
    assert f'value="{shop.pk}" selected' in party
    tag = rf'<input[^>]*name="splits-0-tags" value="{trip.pk}"[^>]*checked'
    assert re.search(tag, body)
