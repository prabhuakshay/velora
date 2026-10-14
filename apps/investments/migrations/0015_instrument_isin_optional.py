from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0014_more_instrument_kinds")]

    operations = [
        migrations.AlterField(
            model_name="instrument",
            name="isin",
            field=models.CharField(
                blank=True, max_length=12, null=True, unique=True, verbose_name="ISIN"
            ),
        ),
        migrations.RemoveField(model_name="instrument", name="manual_price"),
    ]
