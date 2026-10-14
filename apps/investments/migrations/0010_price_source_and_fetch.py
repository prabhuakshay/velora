import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

SOURCES = [("AMFI", "AMFI"), ("NSE", "NSE"), ("Manual", "Manual")]


def source_from_instrument(apps, schema_editor):
    """Give each existing Price its Instrument's Price Source; it has no fetch."""
    prices = apps.get_model("investments", "Price").objects
    prices.filter(instrument__manual_price=True).update(source="Manual")
    automatic = prices.filter(instrument__manual_price=False)
    funds = Q(instrument__kind="mutual_fund")
    automatic.filter(funds).update(source="AMFI")
    automatic.exclude(funds).update(source="NSE")


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0009_price_fetch"),
    ]

    operations = [
        migrations.AddField(
            model_name="price",
            name="source",
            field=models.CharField(choices=SOURCES, default="", max_length=8),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="price",
            name="fetch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="prices",
                to="investments.pricefetch",
            ),
        ),
        migrations.RunPython(source_from_instrument, migrations.RunPython.noop),
    ]
