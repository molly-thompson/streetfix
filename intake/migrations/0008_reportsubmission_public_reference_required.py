from django.db import migrations, models

import intake.models


class Migration(migrations.Migration):
    dependencies = [
        ("intake", "0007_assign_public_references"),
    ]

    operations = [
        migrations.AlterField(
            model_name="reportsubmission",
            name="public_reference",
            field=models.CharField(
                default=intake.models.new_public_reference,
                editable=False,
                help_text=(
                    "Random code a reporter can quote; reveals nothing about volume."
                ),
                max_length=12,
                unique=True,
            ),
        ),
    ]
