from django.db import migrations


class Migration(migrations.Migration):
    # Apart from the data move, as Postgres refuses to alter a table with
    # pending trigger events in the same transaction.
    dependencies = [("cards", "0004_statement_payments")]

    operations = [migrations.RemoveField(model_name="statement", name="transaction")]
