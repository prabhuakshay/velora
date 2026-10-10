import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

STATUSES = {"draft": "waiting", "posted": "posted", "rejected": "rejected"}


def move_lifecycle_to_drafts(apps, schema_editor):
    Draft = apps.get_model("quick_add", "Draft")
    for draft in Draft.objects.select_related("quick_add"):
        quick_add = draft.quick_add
        draft.status = STATUSES.get(quick_add.status, "waiting")
        draft.created_at = quick_add.created_at
        draft.transaction_id = quick_add.transaction_id
        if quick_add.status == "draft":
            draft.posting_error = quick_add.failure_reason
            quick_add.failure_reason = ""
            quick_add.save(update_fields=["failure_reason"])
        draft.save()


def move_lifecycle_back(apps, schema_editor):
    Draft = apps.get_model("quick_add", "Draft")
    for draft in Draft.objects.filter(quick_add__isnull=False).select_related(
        "quick_add"
    ):
        quick_add = draft.quick_add
        quick_add.transaction_id = draft.transaction_id
        if draft.status == "waiting":
            quick_add.failure_reason = draft.posting_error
        quick_add.save(update_fields=["transaction", "failure_reason"])


class Migration(migrations.Migration):
    dependencies = [
        ("quick_add", "0003_draft_protects_its_party"),
        ("transactions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="draft",
            name="source",
            field=models.CharField(
                choices=[
                    ("quick_add", "Quick Add"),
                    ("schedule", "Schedule"),
                    ("manual", "Manual"),
                ],
                default="quick_add",
                max_length=16,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="draft",
            name="status",
            field=models.CharField(
                choices=[
                    ("waiting", "Waiting"),
                    ("posted", "Posted"),
                    ("rejected", "Rejected"),
                ],
                default="waiting",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="draft",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="draft",
            name="posting_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="draft",
            name="transaction",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="draft",
                to="transactions.transaction",
            ),
        ),
        migrations.RunPython(move_lifecycle_to_drafts, move_lifecycle_back),
        migrations.RemoveField(model_name="quickadd", name="transaction"),
        migrations.AlterField(
            model_name="draft",
            name="quick_add",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="draft",
                to="quick_add.quickadd",
            ),
        ),
        migrations.AlterModelOptions(
            name="draft", options={"ordering": ("created_at", "pk")}
        ),
        migrations.AddConstraint(
            model_name="draft",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("quick_add__isnull", False), ("source", "quick_add")
                )
                | models.Q(
                    models.Q(("source", "quick_add"), _negated=True),
                    ("quick_add__isnull", True),
                ),
                name="quick_add_draft_quick_add_iff_source",
                violation_error_message=(
                    "Only a Draft from a Quick Add links to a Quick Add."
                ),
            ),
        ),
    ]
