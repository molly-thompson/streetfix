"""Tests for preserving legacy intake records across migrations."""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from intake.models import IssueCategory


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_existing_submission_link_survives_intake_lifecycle_migration() -> None:
    """Existing links are marked legacy without claiming a triage outcome."""
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [
        ("intake", "0002_seed_contact_methods"),
        next(node for node in latest if node[0] == "employees"),
    ]
    try:
        # Commit cascading deletes before PostgreSQL drops the legacy tables.
        IssueCategory.objects.all().delete()
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        department = old_apps.get_model("employees", "Department").objects.create(
            name="Migration department"
        )
        issue_type = old_apps.get_model("employees", "IssueType").objects.create(
            department=department, name="Migration issue", code="MIGRATION"
        )
        priority = old_apps.get_model("employees", "Priority").objects.get(
            code="NORMAL"
        )
        urgency = old_apps.get_model("employees", "Urgency").objects.get(code="ROUTINE")
        status = old_apps.get_model("employees", "WorkItemStatus").objects.get(
            code="SUBMITTED"
        )
        work_item = old_apps.get_model("employees", "WorkItem").objects.create(
            issue_type=issue_type,
            latitude=Decimal("51.500000"),
            longitude=Decimal("-0.120000"),
            priority=priority,
            urgency=urgency,
            status=status,
        )
        contact_method = old_apps.get_model("intake", "ContactMethod").objects.get(
            code="EMAIL"
        )
        old_submission = old_apps.get_model(
            "intake", "ReportSubmission"
        ).objects.create(
            work_item=work_item,
            contact_method=contact_method,
            updates_requested=False,
            description="A historical report.",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        new_apps = executor.loader.project_state(latest).apps
        submission = new_apps.get_model("intake", "ReportSubmission").objects.get(
            pk=old_submission.pk
        )
        assert submission.work_item_id == work_item.pk
        assert submission.triage_state == "LEGACY_LINKED"
        assert submission.latitude is None
        assert submission.longitude is None
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_existing_submissions_get_distinct_random_references() -> None:
    """Reports saved before references existed each receive their own code."""
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [
        ("intake", "0005_public_report_photos_and_rate_limits"),
        next(node for node in latest if node[0] == "employees"),
    ]
    try:
        executor.migrate(before)
        old = executor.loader.project_state(before).apps.get_model(
            "intake", "ReportSubmission"
        )
        ids = [
            old.objects.create(updates_requested=False, description=f"Report {n}").pk
            for n in range(3)
        ]

        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        new = executor.loader.project_state(latest).apps.get_model(
            "intake", "ReportSubmission"
        )
        references = [new.objects.get(pk=pk).public_reference for pk in ids]
        assert len(set(references)) == 3
        assert all(len(reference) == 8 for reference in references)
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_chat_category_upgrade_preserves_unmatched_rows() -> None:
    """Preserve both matched and ambiguous legacy categories during upgrade."""
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [
        ("intake", "0009_merge_configurability_and_triage"),
        next(node for node in latest if node[0] == "employees"),
    ]
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        category = old_apps.get_model("intake", "IssueCategory")
        department = old_apps.get_model("employees", "Department").objects.create(
            name="Migration team"
        )
        issue = old_apps.get_model("employees", "IssueType").objects.create(
            code="MATCHED", name="Matched issue", department=department
        )
        matched = category.objects.create(
            code="legacy-matched",
            label="Matched issue",
            department_name=department.name,
            issue_type_code=issue.code,
            issue_type_name=issue.name,
        )
        unmatched = category.objects.create(
            code="legacy-unmatched",
            label="Custom issue",
            department_name="Unknown team",
            issue_type_code="CUSTOM",
            issue_type_name="Custom issue",
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        new_apps = executor.loader.project_state(latest).apps
        category = new_apps.get_model("intake", "IssueCategory")
        assert category.objects.get(pk=matched.pk).issue_type_id == issue.pk
        assert category.objects.get(pk=unmatched.pk).issue_type_id is None
    finally:
        MigrationExecutor(connection).migrate(latest)
