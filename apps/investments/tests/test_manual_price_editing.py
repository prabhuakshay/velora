import re
from html import unescape
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.investments.models import Price
from apps.investments.nightly import run_nightly_prices
from apps.investments.tests.conftest import instrument_url, row
from apps.investments.tests.test_price_table import (
    STOCK,
    TODAY,
    enter_price,
    manual_instrument,
    price_rows,
)
from apps.users.tests.conftest import privacy_mode_off_url

if TYPE_CHECKING:
    from django.test import Client

    from apps.investments.tests.conftest import FakePriceSource
    from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_a_manual_price_shows_the_day_it_was_entered(signed_in: Client) -> None:
    enter_price(signed_in, manual_instrument(), "2026-10-01", "100")

    (only,) = price_rows(signed_in, STOCK)

    assert f"Manual · entered {timezone.localdate():%-d %b}" in only


def row_link(client: Client, action: str, day: str = "1 Oct 2026") -> str:
    """The URL behind a Price row's Edit or Delete, found as the user would."""
    html = client.get(instrument_url(STOCK)).content.decode()
    for found in re.findall(r"<tr data-price>(.*?)</tr>", html, re.DOTALL):
        if day in found:
            link = re.search(
                rf'(?:href|action)="([^"]*)"[^>]*aria-label="{action}', found
            )
            assert link, found
            return unescape(link[1])
    raise AssertionError(day)


def test_a_manual_price_can_be_deleted_from_the_table(signed_in: Client) -> None:
    instrument = manual_instrument()
    enter_price(signed_in, instrument, "2026-10-01", "100")
    enter_price(signed_in, instrument, "2026-10-02", "110")

    response = signed_in.post(row_link(signed_in, "Delete"))

    assert response.status_code == 302
    assert [r[:10] for r in price_rows(signed_in, STOCK)] == ["2 Oct 2026"]


def test_a_manual_price_can_be_edited_from_the_table(signed_in: Client) -> None:
    enter_price(signed_in, manual_instrument(), "2026-10-01", "100")
    edit_url = row_link(signed_in, "Edit")
    assert signed_in.get(edit_url).status_code == 200

    response = signed_in.post(edit_url, {"date": "2026-10-02", "price": "105.5"})

    assert response.status_code == 302
    (only,) = price_rows(signed_in, STOCK)
    assert only.startswith("2 Oct 2026 ₹105.5000 — Manual · entered")


def test_editing_onto_another_prices_day_is_refused(signed_in: Client) -> None:
    instrument = manual_instrument()
    enter_price(signed_in, instrument, "2026-10-01", "100")
    enter_price(signed_in, instrument, "2026-10-02", "110")

    response = signed_in.post(
        row_link(signed_in, "Edit"), {"date": "2026-10-02", "price": "105"}
    )

    assert response.status_code == 200
    assert "already a Price for that day" in unescape(response.content.decode())
    assert [r[:20] for r in price_rows(signed_in, STOCK)] == [
        "2 Oct 2026 ₹110.0000",
        "1 Oct 2026 ₹100.0000",
    ]


def test_editing_to_a_price_of_zero_is_refused(signed_in: Client) -> None:
    enter_price(signed_in, manual_instrument(), "2026-10-01", "100")

    response = signed_in.post(
        row_link(signed_in, "Edit"), {"date": "2026-10-01", "price": "0"}
    )

    assert response.status_code == 200
    assert [r[:20] for r in price_rows(signed_in, STOCK)] == ["1 Oct 2026 ₹100.0000"]


def fetched_price(fake_prices: FakePriceSource) -> Price:
    fake_prices.nse = [row(STOCK, "Reliance", "stock", "2950", TODAY)]
    run_nightly_prices(TODAY)
    return Price.objects.get()


def test_a_fetched_price_offers_no_edit_or_delete(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    fetched_price(fake_prices)

    html = signed_in.get(instrument_url(STOCK)).content.decode()

    assert 'aria-label="Edit' not in html
    assert 'aria-label="Delete' not in html


def test_editing_or_deleting_a_fetched_price_is_refused(
    signed_in: Client, fake_prices: FakePriceSource
) -> None:
    pk = fetched_price(fake_prices).pk

    edited = signed_in.post(
        reverse("price_edit", args=[pk]), {"date": "2026-10-14", "price": "1"}
    )
    deleted = signed_in.post(reverse("price_delete", args=[pk]))

    assert (edited.status_code, deleted.status_code) == (404, 404)
    assert [r[:23] for r in price_rows(signed_in, STOCK)] == ["14 Oct 2026 ₹2,950.0000"]


def manual_price_urls(client: Client) -> tuple[str, str]:
    enter_price(client, manual_instrument(), "2026-10-01", "100")
    return row_link(client, "Edit"), row_link(client, "Delete")


def test_editing_and_deleting_wait_for_privacy_mode_to_be_off(
    signed_in: Client, user: User
) -> None:
    edit_url, delete_url = manual_price_urls(signed_in)
    user.privacy_mode = True
    user.save()

    edited = signed_in.post(edit_url, {"date": "2026-10-01", "price": "1"})
    deleted = signed_in.post(delete_url)

    assert edited["Location"] == privacy_mode_off_url(edit_url)
    assert deleted["Location"] == privacy_mode_off_url(delete_url)
    user.privacy_mode = False
    user.save()
    assert [r[:20] for r in price_rows(signed_in, STOCK)] == ["1 Oct 2026 ₹100.0000"]


def test_editing_and_deleting_need_a_sign_in(signed_in: Client) -> None:
    edit_url, delete_url = manual_price_urls(signed_in)
    signed_in.logout()

    for url in (edit_url, delete_url):
        response = signed_in.post(url)
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("login"))


def test_deleting_takes_a_post_only(signed_in: Client) -> None:
    _, delete_url = manual_price_urls(signed_in)

    assert signed_in.get(delete_url).status_code == 405
    assert len(price_rows(signed_in, STOCK)) == 1
