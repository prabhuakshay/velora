from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0016_clear_invalid_isins")]

    operations = [
        migrations.AddConstraint(
            model_name="instrument",
            constraint=models.UniqueConstraint(
                condition=models.Q(isin__isnull=True),
                fields=("name",),
                name="instrument_name_unique_without_isin",
            ),
        ),
    ]
