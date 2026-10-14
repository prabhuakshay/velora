import json
import re
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


def price_history(client: Client) -> str:
    html = client.get(instrument_url(ISIN)).content.decode()
    after = html.split("<caption>Price at each month-end", 1)[1]
    return page_text(after.split("</table>", 1)[0])


def test_the_page_charts_the_price_history(signed_in: Client) -> None:
    instrument = make_instrument(manual_price=False)
    for day, price in [
        ("2026-01-12", "10"),
        ("2026-01-30", "11"),
        ("2026-02-04", "12.5"),
    ]:
        Price.objects.create(instrument=instrument, date=day, price=Decimal(price))

    history = price_history(signed_in)

    assert "30 Jan 2026₹11.0000 4 Feb 2026₹12.5000" in history
    assert "12 Jan 2026" not in history
    assert "<polyline" in signed_in.get(instrument_url(ISIN)).content.decode()


def test_a_single_price_draws_no_chart(signed_in: Client) -> None:
    instrument = make_instrument(manual_price=False)
    Price.objects.create(instrument=instrument, date="2026-01-12", price=Decimal(10))

    assert "<polyline" not in signed_in.get(instrument_url(ISIN)).content.decode()


def test_privacy_mode_hides_the_price_chart(signed_in: Client, user: User) -> None:
    instrument = make_instrument(manual_price=False)
    Price.objects.create(instrument=instrument, date="2026-01-12", price=Decimal(10))
    Price.objects.create(instrument=instrument, date="2026-02-12", price=Decimal(11))
    user.privacy_mode = True
    user.save()

    html = signed_in.get(instrument_url(ISIN)).content.decode()

    assert "<polyline" not in html
    assert "Hidden in Privacy Mode" in page_text(html)


def chart_data(client: Client) -> object:
    html = client.get(instrument_url(ISIN)).content.decode()
    match = re.search(r'id="price-chart-data"[^>]*>(.*?)</script>', html, re.DOTALL)
    return json.loads(match.group(1)) if match else None


def test_the_chart_embeds_every_price_for_hover_and_ranges(signed_in: Client) -> None:
    instrument = make_instrument(manual_price=False)
    Price.objects.create(instrument=instrument, date="2026-01-12", price=Decimal(10))
    Price.objects.create(
        instrument=instrument, date="2026-02-04", price=Decimal("12.5")
    )

    html = signed_in.get(instrument_url(ISIN)).content.decode()

    assert chart_data(signed_in) == [
        ["2026-01-12", "10.0000"],
        ["2026-02-04", "12.5000"],
    ]
    assert "js/price_chart.js" in html
    assert "1M 6M 1Y All" in page_text(html)


def test_privacy_mode_embeds_no_chart_data(signed_in: Client, user: User) -> None:
    instrument = make_instrument(manual_price=False)
    Price.objects.create(instrument=instrument, date="2026-01-12", price=Decimal(10))
    Price.objects.create(instrument=instrument, date="2026-02-12", price=Decimal(11))
    user.privacy_mode = True
    user.save()

    html = signed_in.get(instrument_url(ISIN)).content.decode()

    assert chart_data(signed_in) is None
    assert "2026-02-12" not in html
