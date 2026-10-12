from django.db import migrations


def mark_estimated_card_payments(apps, schema_editor):
    Draft = apps.get_model("quick_add", "Draft")
    Draft.objects.filter(
        status="waiting", source="statement", statement__actual_amount__isnull=True
    ).update(estimated=True)


class Migration(migrations.Migration):
    dependencies = [
        ("cards", "0002_card_emi"),
        ("quick_add", "0012_quick_add_stall_clock_starts_with_its_job"),
    ]

    operations = [
        migrations.RunPython(mark_estimated_card_payments, migrations.RunPython.noop),
    ]
