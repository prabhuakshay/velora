from datetime import date

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("quick_add", "0003_draft_protects_its_party")]
AFTER = [("quick_add", "0004_drafts_own_their_source_and_lifecycle")]


def migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor


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


BEFORE_ESTIMATES = [("quick_add", "0012_quick_add_stall_clock_starts_with_its_job")]
AFTER_ESTIMATES = [("quick_add", "0013_card_payment_drafts_estimated")]


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_waiting_card_payments_of_an_estimate_become_estimated() -> None:
    # The other apps at their latest, as the migration runs against them.
    others = [
        node
        for node in MigrationExecutor(connection).loader.graph.leaf_nodes()
        if node[0] != "quick_add"
    ]
    old = migrate(BEFORE_ESTIMATES).loader.project_state(others + BEFORE_ESTIMATES).apps
    Account = old.get_model("accounts", "Account")
    Statement = old.get_model("cards", "Statement")
    Draft = old.get_model("quick_add", "Draft")
    card = Account.objects.create(
        name="HDFC card",
        kind="liability",
        opening_balance=0,
        opening_balance_date=date(2026, 1, 1),
    )

    def payment_draft(closing: date, actual_amount: str | None) -> None:
        statement = Statement.objects.create(
            card=card,
            period_start=closing.replace(month=closing.month - 1),
            period_end=closing,
            due_date=closing.replace(month=closing.month + 1),
            estimated_amount="1200",
            actual_amount=actual_amount,
        )
        Draft.objects.create(
            source="statement",
            statement=statement,
            date=statement.due_date,
            description=str(closing),
        )

    payment_draft(date(2026, 9, 15), None)
    payment_draft(date(2026, 10, 15), "1450")

    new = migrate(AFTER_ESTIMATES).loader.project_state(others + AFTER_ESTIMATES).apps
    drafts = new.get_model("quick_add", "Draft").objects

    assert dict(drafts.values_list("description", "estimated")) == {
        "2026-09-15": True,
        "2026-10-15": False,
    }
