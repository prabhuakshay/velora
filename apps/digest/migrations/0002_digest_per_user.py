import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def one_per_user(apps, schema_editor):
    """A day's digest went to every user then, so record it for each."""
    digest = apps.get_model("digest", "Digest")
    user = apps.get_model("users", "User")
    days = list(digest.objects.values_list("sent_on", flat=True))
    digest.objects.all().delete()
    digest.objects.bulk_create(
        digest(sent_on=day, user_id=user_id)
        for day in days
        for user_id in user.objects.values_list("pk", flat=True)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("digest", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="digest",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="digests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="digest",
            name="sent_on",
            field=models.DateField(),
        ),
        migrations.RunPython(one_per_user, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="digest",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="digests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="digest",
            constraint=models.UniqueConstraint(
                fields=("sent_on", "user"), name="digest_digest_one_per_user_per_day"
            ),
        ),
    ]
