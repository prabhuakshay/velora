import re
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from apps.accounts.tests.conftest import make_account
from apps.classification.models import Tag
from apps.transactions.models import Split, Transaction

if TYPE_CHECKING:
    from django.test import Client

    from apps.users.models import User

pytestmark = pytest.mark.django_db


def make_split(*tags: Tag) -> Split:
    transaction = Transaction.objects.create(date=date(2026, 3, 1))
    split = transaction.splits.create(
        from_account=make_account(f"Bank {Split.objects.count()}", "asset"),
        to_account=make_account(f"Food {Split.objects.count()}", "expense"),
        amount=Decimal(100),
    )
    split.tags.set(tags)
    return split


def target_choices(body: str) -> list[str]:
    match = re.search(r'<select name="target".*?</select>', body, re.DOTALL)
    assert match
    return re.findall(r'<option value="\d+">([^<]+)</option>', match.group())


@pytest.fixture
def trips() -> tuple[Tag, Tag]:
    """Goa trip merges into Travel: one Split has only Goa trip, one has both."""
    goa, travel = Tag.objects.create(name="Goa trip"), Tag.objects.create(name="Travel")
    make_split(goa)
    make_split(goa, travel)
    make_split(travel)
    return goa, travel


def test_every_tag_row_offers_merge(signed_in: Client) -> None:
    tag = Tag.objects.create(name="Trip", hidden=True)

    body = signed_in.get(reverse("tag_list") + "?show_hidden=1").content.decode()

    assert reverse("tag_merge", args=[tag.pk]) in body


def test_merge_targets_are_other_tags(signed_in: Client) -> None:
    source = Tag.objects.create(name="Goa trip")
    Tag.objects.create(name="Travel")
    Tag.objects.create(name="Food")

    body = signed_in.get(reverse("tag_merge", args=[source.pk])).content.decode()

    assert target_choices(body) == ["Food", "Travel"]


def test_target_cannot_be_the_source(signed_in: Client) -> None:
    source = Tag.objects.create(name="Goa trip")
    make_split(source)

    response = signed_in.post(
        reverse("tag_merge", args=[source.pk]), {"target": source.pk}
    )

    assert response.status_code == 200
    assert b"Select a valid choice" in response.content
    assert Tag.objects.filter(pk=source.pk, splits__isnull=False).exists()


def test_confirmation_shows_how_many_splits_move(
    signed_in: Client, trips: tuple[Tag, Tag]
) -> None:
    goa, _ = trips

    body = signed_in.get(reverse("tag_merge", args=[goa.pk])).content.decode()

    assert "2 Splits will move." in body


def test_merge_moves_splits_to_the_target_once_and_removes_the_source(
    signed_in: Client, trips: tuple[Tag, Tag]
) -> None:
    goa, travel = trips

    response = signed_in.post(
        reverse("tag_merge", args=[goa.pk]), {"target": travel.pk}, follow=True
    )

    assert response.redirect_chain == [(reverse("tag_list"), 302)]
    assert "Merged Goa trip into Travel." in response.content.decode()
    assert not Tag.objects.filter(pk=goa.pk).exists()
    assert [list(s.tags.all()) for s in Split.objects.order_by("pk")] == [
        [travel],
        [travel],
        [travel],
    ]


def test_change_history_records_the_merge(
    signed_in: Client, user: User, trips: tuple[Tag, Tag]
) -> None:
    goa, travel = trips
    moved = list(goa.splits.all())

    signed_in.post(reverse("tag_merge", args=[goa.pk]), {"target": travel.pk})

    reason = "Merged Goa trip into Travel"
    deleted = Tag.history.get(id=goa.pk, history_type="-")
    assert (deleted.history_user, deleted.history_change_reason) == (user, reason)
    for split in moved:
        latest = split.history.latest()
        assert (latest.history_user, latest.history_change_reason) == (user, reason)
        assert [t.tag_id for t in latest.tags.all()] == [travel.pk]


def test_merge_works_with_the_longest_names(signed_in: Client) -> None:
    source = Tag.objects.create(name="a" * 100)
    target = Tag.objects.create(name="b" * 100)
    split = make_split(source)

    signed_in.post(reverse("tag_merge", args=[source.pk]), {"target": target.pk})

    assert not Tag.objects.filter(pk=source.pk).exists()
    assert list(split.tags.all()) == [target]


def test_deleting_an_unused_tag_asks_to_confirm(signed_in: Client) -> None:
    tag = Tag.objects.create(name="Trip")

    body = signed_in.get(reverse("tag_delete", args=[tag.pk])).content.decode()

    assert "This cannot be undone." in body
    assert reverse("tag_merge", args=[tag.pk]) not in body


def test_deleting_an_in_use_tag_offers_merge_or_force_delete(
    signed_in: Client, trips: tuple[Tag, Tag]
) -> None:
    goa, _ = trips

    body = signed_in.get(reverse("tag_delete", args=[goa.pk])).content.decode()

    assert "Goa trip is on 2 Splits." in body
    assert reverse("tag_merge", args=[goa.pk]) in body
    assert "Force delete" in body
    assert "hide" in body


def test_force_delete_removes_the_tag_and_keeps_transactions_and_splits(
    signed_in: Client, trips: tuple[Tag, Tag]
) -> None:
    goa, travel = trips

    response = signed_in.post(reverse("tag_delete", args=[goa.pk]))

    assert response["Location"] == reverse("tag_list")
    assert not Tag.objects.filter(pk=goa.pk).exists()
    assert Transaction.objects.count() == 3
    assert [list(s.tags.all()) for s in Split.objects.order_by("pk")] == [
        [],
        [travel],
        [travel],
    ]


def test_force_delete_is_recorded_in_split_change_history(
    signed_in: Client, user: User, trips: tuple[Tag, Tag]
) -> None:
    goa, travel = trips
    carrying = list(goa.splits.order_by("pk"))

    signed_in.post(reverse("tag_delete", args=[goa.pk]))

    expected = [[], [travel.pk]]
    for split, tags in zip(carrying, expected, strict=True):
        latest = split.history.latest()
        assert (latest.history_user, latest.history_change_reason) == (
            user,
            "Deleted Goa trip",
        )
        assert [t.tag_id for t in latest.tags.all()] == tags
