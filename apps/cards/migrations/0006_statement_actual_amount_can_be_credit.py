from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cards", "0005_remove_statement_transaction")]

    operations = [
        migrations.AlterField(
            model_name="statement",
            name="actual_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "From the real statement, below zero when it shows a credit;"
                    " leave blank to use the estimate."
                ),
                max_digits=15,
                null=True,
            ),
        ),
    ]
