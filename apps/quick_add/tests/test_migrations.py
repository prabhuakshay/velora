from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

if TYPE_CHECKING:
    from collections.abc import Iterator

BEFORE = [("quick_add", "0003_draft_protects_its_party")]
AFTER = [("quick_add", "0004_drafts_own_their_source_and_lifecycle")]


def migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor


@pytest.fixture
def _back_to_latest() -> Iterator[None]:
    yield
    migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_existing_drafts_become_quick_add_drafts_owning_their_lifecycle() -> None:
    old = migrate(BEFORE).loader.project_state(BEFORE).apps
    QuickAdd = old.get_model("quick_add", "QuickAdd")
    Draft = old.get_model("quick_add", "Draft")
    Transaction = old.get_model("transactions", "Transaction")
    recorded = Transaction.objects.create(date=date(2026, 10, 8))
    waiting = QuickAdd.objects.create(
        text="lunch 850", status="draft", failure_reason="Split 1 From: gone"
    )
    posted = QuickAdd.objects.create(
        text="taxi 300", status="posted", transaction=recorded
    )
    rejected = QuickAdd.objects.create(text="coffee 150", status="rejected")
    for quick_add in [waiting, posted, rejected]:
        Draft.objects.create(quick_add=quick_add, date=date(2026, 10, 8))

    new = migrate(AFTER).loader.project_state(AFTER).apps
    drafts = new.get_model("quick_add", "Draft").objects

    assert {
        (draft.quick_add.text, draft.source, draft.status, draft.transaction_id)
        for draft in drafts.select_related("quick_add")
    } == {
        ("lunch 850", "quick_add", "waiting", None),
        ("taxi 300", "quick_add", "posted", recorded.pk),
        ("coffee 150", "quick_add", "rejected", None),
    }
    moved = drafts.get(quick_add__text="lunch 850")
    assert moved.posting_error == "Split 1 From: gone"
    assert moved.quick_add.failure_reason == ""
