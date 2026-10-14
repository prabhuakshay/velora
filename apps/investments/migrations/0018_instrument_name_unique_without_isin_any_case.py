from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("investments", "0017_instrument_name_unique_without_isin")]

    operations = [
        migrations.RemoveConstraint(
            model_name="instrument", name="instrument_name_unique_without_isin"
        ),
        migrations.AddConstraint(
            model_name="instrument",
            constraint=models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(isin__isnull=True),
                name="instrument_name_unique_without_isin",
            ),
        ),
    ]
