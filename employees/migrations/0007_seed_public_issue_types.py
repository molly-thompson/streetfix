"""Seed the issue types that the public report chat has always offered."""

from django.db import migrations

# (department, code, name); position sets the order they are offered in.
ISSUE_TYPES = (
    ("Highways", "POTHOLE", "Pothole"),
    ("Highways", "DAMAGED_SIGN", "Damaged sign"),
    ("Highways", "BLOCKED_DRAIN", "Blocked drain or flooding"),
    ("Street Cleansing", "FLY_TIPPING", "Fly-tipping"),
    ("Street Cleansing", "GRAFFITI", "Graffiti"),
    ("Street Lighting", "STREETLIGHT", "Broken streetlight"),
    ("Parks", "PARKS_TREES", "Parks and trees"),
    ("Triage desk", "OTHER", "Other (needs review)"),
)


def seed_issue_types(apps, schema_editor):
    """Create missing issue types; keep any the team already configured."""
    Department = apps.get_model("employees", "Department")
    IssueType = apps.get_model("employees", "IssueType")
    for position, (department_name, code, name) in enumerate(ISSUE_TYPES):
        existing = IssueType.objects.filter(code=code).first()
        if existing is not None:
            IssueType.objects.filter(pk=existing.pk).update(sort_order=position)
            continue
        department, _ = Department.objects.get_or_create(name=department_name)
        IssueType.objects.get_or_create(
            department=department,
            name=name,
            defaults={"code": code, "sort_order": position},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0006_issue_type_hierarchy"),
    ]

    operations = [
        migrations.RunPython(seed_issue_types, migrations.RunPython.noop),
    ]
