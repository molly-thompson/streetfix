import logging

import django.db.models.deletion
from django.db import migrations, models


logger = logging.getLogger(__name__)


def link_existing_categories(apps, schema_editor):
    """Link only unambiguous legacy configuration without discarding it."""
    Category = apps.get_model("intake", "IssueCategory")
    IssueType = apps.get_model("employees", "IssueType")
    alias = schema_editor.connection.alias
    for category in Category.objects.using(alias).order_by("pk"):
        matches = list(
            IssueType.objects.using(alias).filter(
                code=category.issue_type_code,
                department__name=category.department_name,
                kind="ISSUE",
            )[:2]
        )
        if len(matches) == 1 and not Category.objects.using(alias).filter(
            issue_type_id=matches[0].pk
        ).exists():
            category.issue_type_id = matches[0].pk
            category.save(using=alias, update_fields=["issue_type"])
        else:
            logger.warning(
                "Chat category %s could not be linked uniquely; reconcile it in admin.",
                category.pk,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0009_merge_configurability_and_issue_hierarchy"),
        ("intake", "0009_merge_configurability_and_triage"),
    ]

    operations = [
        migrations.AddField(
            model_name="issuecategory",
            name="issue_type",
            field=models.OneToOneField(
                blank=True,
                limit_choices_to={"kind": "ISSUE"},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="chat_category",
                to="employees.issuetype",
            ),
        ),
        migrations.RunPython(link_existing_categories, migrations.RunPython.noop),
    ]
