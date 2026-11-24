from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("intake", "0005_public_report_photos_and_rate_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportsubmission",
            name="public_reference",
            field=models.CharField(editable=False, max_length=12, null=True),
        ),
    ]
