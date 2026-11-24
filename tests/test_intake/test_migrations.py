"""Tests for preserving legacy intake records across migrations."""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_existing_submission_link_survives_intake_lifecycle_migration() -> None:
    """Existing links are marked legacy without claiming a triage outcome."""
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [
        ("intake", "0002_seed_contact_methods"),
        next(node for node in latest if node[0] == "employees"),
    ]
    try:
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
