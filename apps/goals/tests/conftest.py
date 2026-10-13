from typing import TYPE_CHECKING

from django.urls import reverse

from apps.accounts.tests.conftest import page_text
from apps.goals.models import Allocation, Goal

if TYPE_CHECKING:
    from django.test import Client
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

    from apps.accounts.models import Account
    from apps.investments.models import Instrument


def create_goal(
    client: Client,
    name: str = "House",
    target: str = "1000000",
    target_date: str = "2030-12-31",
    *,
    expect: int = 302,
) -> Goal | None:
    response = client.post(
        reverse("goal_create"),
        {"name": name, "target_amount": target, "target_date": target_date},
    )
    assert response.status_code == expect
    return Goal.objects.filter(name=name).first()


def source(account: Account, instrument: Instrument | None = None) -> str:
    if instrument is None:
        return f"account:{account.pk}"
    return f"holding:{account.pk}:{instrument.pk}"


def allocate(
    client: Client,
    goal: Goal,
    of: str,
    *,
    expect: int = 302,
    **share: str,
) -> Response:
    """Allocate a percent= or amount= of the source to the Goal."""
    response = client.post(
        reverse("allocation_create", args=[goal.pk]),
        {"source": of, "percent": "", "amount": ""} | share,
    )
    assert response.status_code == expect
    return response


def edit_allocation(
    client: Client,
    allocation: Allocation,
    *,
    percent: str = "",
    amount: str = "",
    expect: int = 302,
) -> Response:
    response = client.post(
        reverse("allocation_edit", args=[allocation.pk]),
        {"source": allocation.source_key, "percent": percent, "amount": amount},
    )
    assert response.status_code == expect
    return response


def text(response: Response) -> str:
    return page_text(response.content.decode())


def goals_text(client: Client) -> str:
    response = client.get(reverse("goal_list"))
    assert response.status_code == 200
    return text(response)


def goal_text(client: Client, goal: Goal) -> str:
    response = client.get(reverse("goal_detail", args=[goal.pk]))
    assert response.status_code == 200
    return text(response)
