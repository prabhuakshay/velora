import json
import re
import urllib.request
from datetime import UTC, date, datetime
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.transactions import cloudflare, r2_bucket

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings

pytestmark = pytest.mark.django_db


class FakeCloudflare:
    """Stands in for the Cloudflare client's queries with canned answers.

    An answer that is an exception is raised instead, as a failed query would.
    """

    def __init__(self) -> None:
        self.daily_storage_answer: list[cloudflare.DailyStorage] | Exception = []
        self.monthly_operations_answer: dict[str, int] | Exception = {}

    def daily_storage(self) -> list[cloudflare.DailyStorage]:
        if isinstance(self.daily_storage_answer, Exception):
            raise self.daily_storage_answer
        return self.daily_storage_answer

    def monthly_operations(self) -> dict[str, int]:
        if isinstance(self.monthly_operations_answer, Exception):
            raise self.monthly_operations_answer
        return self.monthly_operations_answer


@pytest.fixture
def fake_cloudflare(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> FakeCloudflare:
    settings.CLOUDFLARE_ACCOUNT_ID = "test-account"
    settings.CLOUDFLARE_API_TOKEN = "test-token"
    fake = FakeCloudflare()
    monkeypatch.setattr(cloudflare, "daily_storage", fake.daily_storage)
    monkeypatch.setattr(cloudflare, "monthly_operations", fake.monthly_operations)
    return fake


def text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def analytics(client: Client) -> str:
    return client.get(reverse("storage_analytics")).content.decode()


def test_storage_page_loads_the_analytics_section_when_configured(
    signed_in: Client, fake_cloudflare: FakeCloudflare
) -> None:
    page = signed_in.get(reverse("storage")).content.decode()

    assert f'hx-get="{reverse("storage_analytics")}"' in page
    assert 'hx-trigger="load"' in page


def test_without_credentials_the_analytics_section_is_absent(
    signed_in: Client,
) -> None:
    page = signed_in.get(reverse("storage"))

    assert page.status_code == 200
    assert reverse("storage_analytics") not in page.content.decode()
    assert signed_in.get(reverse("storage_analytics")).status_code == 404


def test_analytics_section_needs_sign_in(
    client: Client, fake_cloudflare: FakeCloudflare
) -> None:
    url = reverse("storage_analytics")

    response = client.get(url)

    assert response.status_code == 302
    assert response["Location"] == f"{reverse('login')}?next={url}"


@pytest.mark.parametrize("error", [OSError("timed out"), ValueError("bad reply")])
def test_query_error_shows_a_short_note_instead_of_the_chart(
    signed_in: Client, fake_cloudflare: FakeCloudflare, error: Exception
) -> None:
    fake_cloudflare.daily_storage_answer = error

    response = signed_in.get(reverse("storage_analytics"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Couldn't reach Cloudflare" in text(html)
    assert "<rect" not in html


def test_no_storage_data_yet_shows_a_note(
    signed_in: Client, fake_cloudflare: FakeCloudflare
) -> None:
    html = analytics(signed_in)

    assert "No storage data from Cloudflare yet." in text(html)
    assert "<rect" not in html


def test_chart_shows_one_bar_per_day_with_readable_sizes(
    signed_in: Client, fake_cloudflare: FakeCloudflare
) -> None:
    fake_cloudflare.daily_storage_answer = [
        cloudflare.DailyStorage(day=date(2026, 10, 8), size=1024 * 1024),
        cloudflare.DailyStorage(day=date(2026, 10, 9), size=3 * 1024 * 1024),
        cloudflare.DailyStorage(day=date(2026, 10, 10), size=2 * 1024 * 1024),
    ]

    html = analytics(signed_in)

    assert text(html).startswith(" From Cloudflare analytics ")
    assert html.count("<rect") == 3
    shown = text(html).replace("\xa0", " ")
    assert "8 Oct 2026: 1.0 MB" in shown
    assert "9 Oct 2026: 3.0 MB" in shown
    assert "10 Oct 2026: 2.0 MB" in shown
    assert "Latest 2.0 MB · Peak 3.0 MB" in shown


def test_operations_are_totalled_into_class_a_and_class_b(
    signed_in: Client, fake_cloudflare: FakeCloudflare
) -> None:
    fake_cloudflare.monthly_operations_answer = {
        "PutObject": 120,
        "ListObjects": 30,
        "GetObject": 2500,
        "HeadObject": 40,
        "DeleteObject": 7,
    }

    shown = text(analytics(signed_in))

    assert "Class A 150" in shown
    assert "Class B 2540" in shown


def test_operations_table_lists_every_action_with_its_count(
    signed_in: Client, fake_cloudflare: FakeCloudflare
) -> None:
    fake_cloudflare.monthly_operations_answer = {
        "PutObject": 120,
        "GetObject": 2500,
        "DeleteObject": 7,
        "SomeNewAction": 3,
    }

    shown = text(analytics(signed_in))

    assert "GetObject 2500 PutObject 120 DeleteObject 7 SomeNewAction 3" in shown


def test_no_operations_this_month_shows_zero_totals_and_a_note(
    signed_in: Client, fake_cloudflare: FakeCloudflare
) -> None:
    shown = text(analytics(signed_in))

    assert "Class A 0 Class B 0" in shown
    assert "No operations this month yet." in shown


@pytest.mark.parametrize("error", [OSError("timed out"), ValueError("bad reply")])
def test_operations_query_error_shows_a_note_and_keeps_the_chart(
    signed_in: Client, fake_cloudflare: FakeCloudflare, error: Exception
) -> None:
    fake_cloudflare.daily_storage_answer = [
        cloudflare.DailyStorage(day=date(2026, 10, 10), size=1024),
    ]
    fake_cloudflare.monthly_operations_answer = error

    response = signed_in.get(reverse("storage_analytics"))

    assert response.status_code == 200
    html = response.content.decode()
    shown = text(html)
    assert "Couldn't reach Cloudflare for operations analytics." in shown
    assert "Class A" not in shown
    assert html.count("<rect") == 1


def cloudflare_responds(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, account: object
) -> list[dict[str, str]]:
    """Answer every Cloudflare query with this account node; return the variables."""
    settings.CLOUDFLARE_ACCOUNT_ID = "test-account"
    settings.CLOUDFLARE_API_TOKEN = "test-token"
    monkeypatch.setattr(r2_bucket, "bucket_name", lambda: "attachments")
    sent: list[dict[str, str]] = []

    def urlopen(request: urllib.request.Request, **_kwargs: object) -> BytesIO:
        sent.append(json.loads(request.data)["variables"])  # type: ignore[arg-type]
        body = {"data": {"viewer": {"accounts": [account]}}}
        return BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return sent


@pytest.mark.parametrize(
    "account",
    [
        {},
        {"r2StorageAdaptiveGroups": None, "r2OperationsAdaptiveGroups": None},
        {
            "r2StorageAdaptiveGroups": [
                {"max": None, "dimensions": {"datetime": "2026-10-10T00:00:00Z"}}
            ],
            "r2OperationsAdaptiveGroups": [
                {"sum": {"requests": None}, "dimensions": {"actionType": "GetObject"}}
            ],
        },
    ],
    ids=["no datasets", "null datasets", "null values"],
)
def test_a_response_of_the_wrong_shape_shows_a_note_per_part(
    signed_in: Client,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    account: object,
) -> None:
    cloudflare_responds(settings, monkeypatch, account)

    response = signed_in.get(reverse("storage_analytics"))

    assert response.status_code == 200
    shown = text(response.content.decode())
    assert "Couldn't reach Cloudflare for storage analytics." in shown
    assert "Couldn't reach Cloudflare for operations analytics." in shown


def test_operations_count_from_the_start_of_the_local_calendar_month(
    signed_in: Client, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.TIME_ZONE = "Asia/Kolkata"
    # 1 Oct 01:30 in Kolkata, still September in UTC; in the past, so the
    # session stays valid.
    now = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
    monkeypatch.setattr(timezone, "now", lambda: now)
    sent = cloudflare_responds(
        settings,
        monkeypatch,
        {"r2StorageAdaptiveGroups": [], "r2OperationsAdaptiveGroups": []},
    )

    analytics(signed_in)

    # The chart's query covers the last weeks, so it starts in an earlier month.
    starts = sorted(variables["start"] for variables in sent)
    assert starts[-1] == "2026-09-30T18:30:00+00:00"
