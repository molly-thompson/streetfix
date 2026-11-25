import secrets

from django.db import migrations

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def assign_references(apps, schema_editor):
    """Give every existing submission its own random public reference."""
    submission = apps.get_model("intake", "ReportSubmission")
    manager = submission.objects.using(schema_editor.connection.alias)
    used = set()
    for pk in manager.filter(public_reference__isnull=True).values_list(
        "pk", flat=True
    ):
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        while code in used:
            code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        used.add(code)
        manager.filter(pk=pk).update(public_reference=code)


class Migration(migrations.Migration):
    dependencies = [
        ("intake", "0006_reportsubmission_public_reference"),
    ]

    operations = [
        migrations.RunPython(assign_references, migrations.RunPython.noop),
    ]
