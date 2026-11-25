from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("site_settings", "0006_alter_themesettings_disabled_opacity_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="siteconfiguration",
            name="reference_prefix",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
