import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Free the Transaction's `statement` name for the link that replaces it."""

    dependencies = [
        ("cards", "0002_card_emi"),
        ("transactions", "0004_transaction_date_indexed"),
    ]

    operations = [
        migrations.AlterField(
            model_name="statement",
            name="transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="transactions.transaction",
            ),
        ),
    ]
