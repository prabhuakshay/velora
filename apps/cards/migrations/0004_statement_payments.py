from django.db import migrations


def link_payments(apps, schema_editor):
    Statement = apps.get_model("cards", "Statement")
    Transaction = apps.get_model("transactions", "Transaction")
    for statement in Statement.objects.filter(transaction__isnull=False):
        Transaction.objects.filter(pk=statement.transaction_id).update(
            statement=statement
        )


def unlink_payments(apps, schema_editor):
    Statement = apps.get_model("cards", "Statement")
    Transaction = apps.get_model("transactions", "Transaction")
    # Only one payment fits the one-to-one link; keep the latest.
    for payment in Transaction.objects.filter(statement__isnull=False).order_by(
        "date", "pk"
    ):
        Statement.objects.filter(pk=payment.statement_id).update(transaction=payment)


class Migration(migrations.Migration):
    dependencies = [
        ("cards", "0003_statement_transaction_freed"),
        ("transactions", "0005_transaction_statement"),
    ]

    operations = [
        migrations.RunPython(link_payments, unlink_payments),
    ]
