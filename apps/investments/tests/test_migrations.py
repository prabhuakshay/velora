from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

if TYPE_CHECKING:
    from django.db.migrations.state import StateApps

BEFORE_TEJAS = [("investments", "0012_instrument_history_checked")]
AFTER_TEJAS = [("investments", "0013_move_tejas_to_real_isin")]


def migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor


Nodes = list[tuple[str, str]]


def tejas_states() -> tuple[StateApps, Nodes]:
    # The other apps at their latest, as the migration runs against them.
    others = [
        node
        for node in MigrationExecutor(connection).loader.graph.leaf_nodes()
        if node[0] != "investments"
    ]
    old = migrate(BEFORE_TEJAS).loader.project_state(others + BEFORE_TEJAS).apps
    return old, others


def migrate_tejas(others: Nodes) -> StateApps:
    return migrate(AFTER_TEJAS).loader.project_state(others + AFTER_TEJAS).apps


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_tejas_records_move_to_the_real_isin_without_a_merger() -> None:
    old, others = tejas_states()
    Instrument = old.get_model("investments", "Instrument")
    InvestmentEvent = old.get_model("investments", "InvestmentEvent")
    DraftInvestment = old.get_model("investments", "DraftInvestment")
    Draft = old.get_model("quick_add", "Draft")
    Schedule = old.get_model("schedules", "Schedule")
    Account = old.get_model("accounts", "Account")
    Goal = old.get_model("goals", "Goal")
    Allocation = old.get_model("goals", "Allocation")
    made_up = Instrument.objects.create(
        isin="TEJASNET", name="Tejas", kind="stock", manual_price=True
    )
    Instrument.objects.create(
        isin="INE010J01012", name="Tejas Networks Ltd", kind="stock"
    )
    other = Instrument.objects.create(
        isin="INE002A01018", name="Reliance Industries", kind="stock"
    )
    made_up.prices.create(date=date(2026, 9, 1), price="600", source="Manual")
    broker = Account.objects.create(
        name="Zerodha",
        kind="asset",
        opening_balance=0,
        opening_balance_date=date(2026, 1, 1),
        investment_mode="holds_cash",
    )
    InvestmentEvent.objects.create(
        account=broker,
        instrument=made_up,
        kind="buy",
        date=date(2026, 3, 2),
        units="10",
        amount="6000",
    )
    InvestmentEvent.objects.create(
        account=broker,
        instrument=other,
        new_instrument=made_up,
        kind="merger",
        date=date(2026, 4, 1),
        units="5",
    )
    Schedule.objects.create(
        start_date=date(2026, 1, 5),
        sip_account=broker,
        sip_instrument=made_up,
    )
    DraftInvestment.objects.create(
        draft=Draft.objects.create(source="manual", date=date(2026, 9, 2)),
        account=broker,
        instrument=made_up,
        kind="buy",
        units="1",
        amount="600",
    )
    goal = Goal.objects.create(
        name="House", target_amount="100000", target_date=date(2030, 1, 1)
    )
    Allocation.objects.create(
        goal=goal, account=broker, instrument=made_up, percent="50"
    )

    new = migrate_tejas(others)
    Instrument = new.get_model("investments", "Instrument")
    InvestmentEvent = new.get_model("investments", "InvestmentEvent")

    assert not Instrument.objects.filter(isin="TEJASNET").exists()
    assert sorted(
        InvestmentEvent.objects.values_list(
            "kind", "instrument__isin", "new_instrument__isin"
        )
    ) == [
        ("buy", "INE010J01012", None),
        ("merger", "INE002A01018", "INE010J01012"),
    ]
    assert list(
        new.get_model("schedules", "Schedule").objects.values_list(
            "sip_instrument__isin", flat=True
        )
    ) == ["INE010J01012"]
    assert list(
        new.get_model("investments", "DraftInvestment").objects.values_list(
            "instrument__isin", flat=True
        )
    ) == ["INE010J01012"]
    assert list(
        new.get_model("goals", "Allocation").objects.values_list(
            "instrument__isin", flat=True
        )
    ) == ["INE010J01012"]


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_tejas_move_changes_nothing_without_both_instruments() -> None:
    old, others = tejas_states()
    Instrument = old.get_model("investments", "Instrument")
    Instrument.objects.create(isin="TEJASNET", name="Tejas", kind="stock")

    new = migrate_tejas(others)

    assert list(
        new.get_model("investments", "Instrument").objects.values_list(
            "isin", flat=True
        )
    ) == ["TEJASNET"]


@pytest.mark.usefixtures("_back_to_latest")
@pytest.mark.django_db(transaction=True)
def test_tejas_move_runs_twice_harmlessly() -> None:
    old, others = tejas_states()
    Instrument = old.get_model("investments", "Instrument")
    Instrument.objects.create(isin="TEJASNET", name="Tejas", kind="stock")
    Instrument.objects.create(isin="INE010J01012", name="Tejas Networks", kind="stock")

    migrate_tejas(others)
    migrate(BEFORE_TEJAS)
    new = migrate_tejas(others)

    assert list(
        new.get_model("investments", "Instrument").objects.values_list(
            "isin", flat=True
        )
    ) == ["INE010J01012"]
