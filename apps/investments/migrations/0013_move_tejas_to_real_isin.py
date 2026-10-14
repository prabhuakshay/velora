"""Move Tejas Networks off the made-up TEJASNET Instrument onto its real ISIN.

A data correction, not a Merger, so no corporate action shows up in its
Lots or XIRR. It does nothing unless both Instruments exist.
"""

from django.db import migrations

MADE_UP = "TEJASNET"
REAL = "INE010J01012"


def move_tejas(apps, schema_editor):
    """Repoint everything on TEJASNET to the real ISIN, then delete TEJASNET."""
    Instrument = apps.get_model("investments", "Instrument")
    made_up = Instrument.objects.filter(isin=MADE_UP).first()
    real = Instrument.objects.filter(isin=REAL).first()
    if made_up is None or real is None:
        return
    apps.get_model("investments", "InvestmentEvent").objects.filter(
        instrument=made_up
    ).update(instrument=real)
    apps.get_model("investments", "InvestmentEvent").objects.filter(
        new_instrument=made_up
    ).update(new_instrument=real)
    apps.get_model("investments", "DraftInvestment").objects.filter(
        instrument=made_up
    ).update(instrument=real)
    apps.get_model("schedules", "Schedule").objects.filter(
        sip_instrument=made_up
    ).update(sip_instrument=real)
    allocations = apps.get_model("goals", "Allocation").objects
    for allocation in allocations.filter(instrument=made_up):
        # A Goal already holding the real one keeps that; this one goes
        # with the made-up Instrument.
        if not allocations.filter(
            goal=allocation.goal_id, account=allocation.account_id, instrument=real
        ).exists():
            allocation.instrument = real
            allocation.save(update_fields=["instrument"])
    made_up.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0012_instrument_history_checked"),
        ("schedules", "0008_sip"),
        ("goals", "0002_goal_projection"),
    ]

    operations = [migrations.RunPython(move_tejas, migrations.RunPython.noop)]
