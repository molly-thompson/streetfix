"""Tests for deterministic pattern discovery."""

from decimal import Decimal

import pytest
from django.utils import timezone

from analytics.services import discover_patterns
from employees.organisation_models import Department, IssueType
from employees.work_models import (
    Priority,
    Urgency,
    WorkItem,
    WorkItemStatus,
)

pytestmark = pytest.mark.django_db


def test_insufficient_data_is_reported_without_findings() -> None:
    """Small datasets must not produce speculative discoveries."""
    result = discover_patterns(WorkItem.objects.none())

    assert result["record_count"] == 0
    assert result["findings"] == []
    assert "at least 20 records" in str(result["limitations"])


def test_issue_type_concentration_is_traceable() -> None:
    """A dominant category should expose observed support and record IDs."""
    department = Department.objects.create(name="Analytics roads")
    issue_type = IssueType.objects.create(
        department=department,
        name="Potholes",
        code="ANALYTICS_POTHOLE",
    )
    other_type = IssueType.objects.create(
        department=department,
        name="Streetlights",
        code="ANALYTICS_LIGHT",
    )
    priority = Priority.objects.get(code="NORMAL")
    urgency = Urgency.objects.get(code="ROUTINE")
    status = WorkItemStatus.objects.get(code="SUBMITTED")

    for index in range(24):
        WorkItem.objects.create(
            issue_type=issue_type if index < 18 else other_type,
            latitude=Decimal("51.500000"),
            longitude=Decimal("-0.120000"),
            priority=priority,
            urgency=urgency,
            status=status,
        )

    result = discover_patterns(
        WorkItem.objects.filter(issue_type__department=department)
    )

    concentration = [
        finding
        for finding in result["findings"]
        if finding["kind"] == "concentration" and "Potholes" in finding["title"]
    ]
    assert concentration
    assert "18 records" in concentration[0]["description"]
    assert len(concentration[0]["supporting_record_ids"]) == 18
    assert concentration[0]["caveat"]


def test_temporal_pattern_uses_database_records() -> None:
    """A repeated month should produce supporting work item IDs."""
    department = Department.objects.create(name="Analytics temporal")
    issue_type = IssueType.objects.create(
        department=department,
        name="Damage",
        code="ANALYTICS_DAMAGE",
    )
    priority = Priority.objects.get(code="NORMAL")
    urgency = Urgency.objects.get(code="ROUTINE")
    status = WorkItemStatus.objects.get(code="SUBMITTED")
    for index in range(24):
        work_item = WorkItem.objects.create(
            issue_type=issue_type,
            latitude=Decimal("51.500000"),
            longitude=Decimal("-0.120000"),
            priority=priority,
            urgency=urgency,
            status=status,
        )
        month = 6 if index < 20 else 5
        WorkItem.objects.filter(pk=work_item.pk).update(
            created_at=timezone.now().replace(year=2025, month=month, day=1)
        )

    result = discover_patterns(
        WorkItem.objects.filter(issue_type__department=department)
    )

    temporal = [
        finding for finding in result["findings"] if finding["kind"] == "temporal"
    ]
    assert temporal
    assert all(finding["supporting_record_ids"] for finding in temporal)
