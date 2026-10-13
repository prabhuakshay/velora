from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.conftest import page_text
from apps.investments.models import Instrument, Price
from apps.investments.tests.conftest import instrument_page, instrument_url
from apps.users.models import NumberFormat
from apps.users.tests.conftest import privacy_mode_off_url

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db

ISIN = "INE000000001"


def make_instrument(*, manual_price: bool) -> Instrument:
    return Instrument.objects.create(
        isin=ISIN, name="Unlisted Co", kind="stock", manual_price=manual_price
    )


def add_price_url(instrument: Instrument) -> str:
    return reverse("instrument_add_price", args=[instrument.pk])


def test_a_price_entered_by_hand_becomes_the_latest(signed_in: Client) -> None:
    instrument = make_instrument(manual_price=True)
    today = timezone.localdate()

    response = signed_in.post(
        add_price_url(instrument), {"date": today, "price": "1234.5678"}
    )

    assert response.status_code == 302
    page = instrument_page(signed_in, ISIN)
    assert f"₹1,234.5678 on {today:%-d %b %Y}" in page


def test_a_second_price_for_the_same_day_replaces_the_first(
    signed_in: Client,
) -> None:
    instrument = make_instrument(manual_price=True)
    today = timezone.localdate()
    signed_in.post(add_price_url(instrument), {"date": today, "price": "10"})

    signed_in.post(add_price_url(instrument), {"date": today, "price": "12"})

    assert "₹12.0000" in instrument_page(signed_in, ISIN)


@pytest.mark.parametrize(
    ("days_ahead", "price", "error"),
    [
        (1, "10", "Pick today or earlier."),
        (0, "0", "Ensure this value is greater than or equal to 0.0001."),
    ],
)
def test_a_bad_price_is_refused(
    signed_in: Client, days_ahead: int, price: str, error: str
) -> None:
    instrument = make_instrument(manual_price=True)
    when = timezone.localdate() + timedelta(days=days_ahead)

    response = signed_in.post(add_price_url(instrument), {"date": when, "price": price})

    assert response.status_code == 200
    assert error in page_text(response.content.decode())
    assert "No Price yet" in instrument_page(signed_in, ISIN)


def test_an_instrument_with_an_automatic_price_takes_none_by_hand(
    signed_in: Client,
) -> None:
    instrument = make_instrument(manual_price=False)

    assert "Enter a Price" not in instrument_page(signed_in, ISIN)
    response = signed_in.post(
        add_price_url(instrument), {"date": timezone.localdate(), "price": "10"}
    )

    assert response.status_code == 404
    assert "No Price yet" in instrument_page(signed_in, ISIN)


def test_privacy_mode_masks_the_price(signed_in: Client, user: User) -> None:
    instrument = make_instrument(manual_price=False)
    Price.objects.create(
        instrument=instrument, date=timezone.localdate(), price=Decimal("2950.15")
    )
    user.privacy_mode = True
    user.save()

    page = instrument_page(signed_in, ISIN)

    assert "2,950" not in page
    assert "₹••••" in page


def test_entering_a_price_waits_for_privacy_mode_to_be_off(
    signed_in: Client, user: User
) -> None:
    instrument = make_instrument(manual_price=True)
    user.privacy_mode = True
    user.save()

    response = signed_in.post(
        add_price_url(instrument), {"date": timezone.localdate(), "price": "10"}
    )

    assert response["Location"] == privacy_mode_off_url(add_price_url(instrument))
    assert not Price.objects.exists()


def test_the_price_follows_the_number_format(signed_in: Client, user: User) -> None:
    instrument = make_instrument(manual_price=False)
    Price.objects.create(
        instrument=instrument, date=timezone.localdate(), price=Decimal("1234567.5")
    )
    assert "₹12,34,567.5000" in instrument_page(signed_in, ISIN)

    user.number_format = NumberFormat.INTERNATIONAL
    user.save()

    assert "₹1,234,567.5000" in instrument_page(signed_in, ISIN)


def test_the_page_needs_a_sign_in(client: Client) -> None:
    make_instrument(manual_price=False)

    assert client.get(instrument_url(ISIN)).status_code == 302
