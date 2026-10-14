from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("investments", "0013_move_tejas_to_real_isin")]

    operations = [
        migrations.AlterField(
            model_name="instrument",
            name="kind",
            field=models.CharField(
                choices=[
                    ("mutual_fund", "Mutual fund"),
                    ("stock", "Stock"),
                    ("etf", "ETF"),
                    ("gold", "Gold"),
                    ("bond", "Bond"),
                    ("reit_invit", "REIT/InvIT"),
                    ("other", "Other"),
                ],
                max_length=20,
            ),
        ),
    ]
