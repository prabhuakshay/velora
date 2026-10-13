from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.goals.models import Goal
from apps.goals.tests.conftest import create_goal, goal_text, goals_text, text

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_a_new_goal_is_listed_with_its_target_and_date(signed_in: Client) -> None:
    create_goal(signed_in, "House", "2500000", "2031-03-31")

    page = goals_text(signed_in)

    assert "House" in page
    assert "₹0.00 of ₹25,00,000.00" in page
    assert "by 31 Mar 2031" in page


def test_the_goals_list_says_when_there_are_none(signed_in: Client) -> None:
    assert "No Goals yet" in goals_text(signed_in)


def test_a_goal_needs_a_name_target_and_date(signed_in: Client) -> None:
    response = signed_in.post(reverse("goal_create"), {"name": ""})

    assert response.status_code == 200
    assert "This field is required" in text(response)
    assert not Goal.objects.exists()


def test_a_goal_target_must_be_above_nothing(signed_in: Client) -> None:
    create_goal(signed_in, "House", "0", expect=200)

    assert not Goal.objects.exists()


def test_a_goal_can_be_renamed_and_retargeted(signed_in: Client) -> None:
    goal = create_goal(signed_in)
    assert goal is not None

    response = signed_in.post(
        reverse("goal_edit", args=[goal.pk]),
        {"name": "Flat", "target_amount": "500000", "target_date": "2029-06-30"},
    )

    assert response.status_code == 302
    page = goal_text(signed_in, goal)
    assert "Flat" in page
    assert "₹5,00,000.00" in page
    assert "30 Jun 2029" in page


def test_a_goal_name_is_unique_ignoring_case(signed_in: Client) -> None:
    create_goal(signed_in, "House")

    create_goal(signed_in, "HOUSE", expect=200)

    assert Goal.objects.count() == 1


def test_a_goal_can_be_deleted(signed_in: Client) -> None:
    goal = create_goal(signed_in)
    assert goal is not None
    url = reverse("goal_delete", args=[goal.pk])

    assert "Delete Goal" in text(signed_in.get(url))
    response = signed_in.post(url)

    assert response["Location"] == reverse("goal_list")
    assert "No Goals yet" in goals_text(signed_in)


def test_the_goal_page_of_an_unknown_goal_is_not_found(signed_in: Client) -> None:
    assert signed_in.get(reverse("goal_detail", args=[999])).status_code == 404


@pytest.mark.parametrize("name", ["goal_list", "goal_create"])
def test_anonymous_is_sent_to_log_in(client: Client, name: str) -> None:
    url = reverse(name)

    response = client.get(url)

    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_goals_has_its_own_nav_item_after_investments(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    investments = body.index(f'href="{reverse("investments_overview")}"')
    goals = body.index(f'href="{reverse("goal_list")}"')
    assert investments < goals


def test_the_goals_nav_item_is_current_on_every_goal_page(signed_in: Client) -> None:
    goal = create_goal(signed_in)
    assert goal is not None
    current = f'href="{reverse("goal_list")}" aria-current="page"'

    for url in (
        reverse("goal_list"),
        reverse("goal_create"),
        reverse("goal_detail", args=[goal.pk]),
        reverse("goal_edit", args=[goal.pk]),
        reverse("allocation_create", args=[goal.pk]),
    ):
        assert current in signed_in.get(url).content.decode(), url
