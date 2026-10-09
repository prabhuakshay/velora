from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.test_balance import opening
from apps.accounts.tests.test_net_worth import home_page
from apps.users.tests.test_number_format import use_format

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def profile_group_tag(body: str) -> str:
    before_summary = body[: body.index("Profile\n")]
    return before_summary.rsplit("<details", 1)[1].split(">", maxsplit=1)[0]


def test_preferences_needs_sign_in(client: Client) -> None:
    url = reverse("preferences")

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


def test_preferences_shows_current_number_format(signed_in: Client, user: User) -> None:
    use_format(user, "international")

    page = signed_in.get(reverse("preferences")).content.decode()

    assert '<option value="international" selected>' in page


def test_saving_preferences_stays_on_page_and_applies(
    signed_in: Client, user: User
) -> None:
    opening("Bank", "asset", "1234567")

    response = signed_in.post(
        reverse("preferences"), {"number_format": "international"}, follow=True
    )

    assert response.redirect_chain == [(reverse("preferences"), 302)]
    assert "Preferences saved." in response.content.decode()
    user.refresh_from_db()
    assert user.number_format == "international"
    assert "Net Worth ₹1,234,567.00" in home_page(signed_in)


def test_switching_back_to_indian(signed_in: Client, user: User) -> None:
    use_format(user, "international")
    opening("Bank", "asset", "1234567")

    signed_in.post(reverse("preferences"), {"number_format": "indian"})

    assert "Net Worth ₹12,34,567.00" in home_page(signed_in)


def test_invalid_number_format_is_rejected(signed_in: Client, user: User) -> None:
    response = signed_in.post(reverse("preferences"), {"number_format": "roman"})

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.number_format == "indian"


def test_number_format_change_is_in_user_history(signed_in: Client, user: User) -> None:
    signed_in.post(reverse("preferences"), {"number_format": "international"})

    assert user.history.first().number_format == "international"


def test_sidebar_links_preferences_above_change_password(signed_in: Client) -> None:
    body = signed_in.get(reverse("index")).content.decode()

    assert "open" not in profile_group_tag(body)
    assert body.index(reverse("preferences")) < body.index(reverse("password_change"))


def test_profile_group_opens_on_preferences(signed_in: Client) -> None:
    body = signed_in.get(reverse("preferences")).content.decode()

    assert "open" in profile_group_tag(body)
    assert f'href="{reverse("preferences")}" class="nav-link nav-link-active"' in body
