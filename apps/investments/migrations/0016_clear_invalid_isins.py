"""Clear every ISIN that is not a real one, so the Instrument is priced by hand.

It keeps its name and its records. Should two then share a name, in any case,
the later ones get their old ISIN appended to tell them apart, and a number
too should that name be taken as well.
"""

from itertools import chain, count

from django.db import migrations

from apps.investments.isin import is_valid_isin


def clear_invalid_isins(apps, schema_editor):
    """Set the made-up ISINs to none, renaming any that clash by name."""
    Instrument = apps.get_model("investments", "Instrument")
    for instrument in Instrument.objects.exclude(isin=None).order_by("pk"):
        if is_valid_isin(instrument.isin):
            continue
        instrument.name = _free_name(Instrument, instrument.name, instrument.isin)
        instrument.isin = None
        instrument.save(update_fields=["isin", "name"])


def _free_name(Instrument, name, isin):
    tagged = f"{name} ({isin})"
    names = chain([name, tagged], (f"{tagged} {n}" for n in count(2)))
    return next(
        candidate
        for candidate in names
        if not Instrument.objects.filter(isin=None, name__iexact=candidate).exists()
    )


class Migration(migrations.Migration):
    dependencies = [("investments", "0015_instrument_isin_optional")]

    operations = [migrations.RunPython(clear_invalid_isins, migrations.RunPython.noop)]
