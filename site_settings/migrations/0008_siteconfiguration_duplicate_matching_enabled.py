from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("site_settings", "0007_alter_siteconfiguration_reference_prefix"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfiguration",
            name="duplicate_matching_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Enable reviewer-requested advisory matching after local evaluation."
                ),
            ),
        ),
    ]
