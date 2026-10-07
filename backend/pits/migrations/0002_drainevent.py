# Generated for seven-day drain board

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pits", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DrainEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("drained_at", models.DateTimeField()),
                ("operator", models.CharField(blank=True, max_length=64)),
                (
                    "pit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="drain_events",
                        to="pits.pit",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["drained_at"], name="pits_draine_drained_0bbbd2_idx")],
            },
        ),
    ]
