import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cards", "0003_statement_transaction_freed"),
        ("transactions", "0004_transaction_date_indexed"),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="statement",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payments",
                to="cards.statement",
            ),
        ),
    ]
