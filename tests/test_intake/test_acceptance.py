"""Tests for human acceptance into operational work."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from employees.organisation_models import Department, Employee, IssueType
from employees.work_models import WorkItem
from intake.models import ReportSubmission, TriageAttempt
from intake.services.acceptance import accept_report

pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewed_report() -> ReportSubmission:
    """Provide a report with a location awaiting review."""
    return ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        triage_state="NEEDS_REVIEW",
        latitude=Decimal("51.5"),
        longitude=Decimal("-0.12"),
    )


@pytest.fixture
def reviewer(make_employee: Callable[..., Employee]) -> Employee:
    """Provide an authorized reviewer."""
    employee = make_employee()
    employee.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    return employee


@pytest.fixture
def issue_type() -> IssueType:
    """Provide a routable issue type."""
    department = Department.objects.create(name="Facilities")
    return IssueType.objects.create(name="Damage", code="DAMAGE", department=department)


def decisions(issue: IssueType) -> dict[str, Any]:
    """Return a complete set of explicitly confirmed review decisions."""
    return {
        "issue_type_id": issue.pk,
        "priority_code": "HIGH",
        "urgency_code": "SOON",
        "scope_confirmed": True,
        "not_duplicate_confirmed": True,
        "location_confirmed": True,
        "reason": "Confirmed from report and records.",
    }


def test_acceptance_creates_one_triaged_work_item_and_audit(
    reviewed_report: ReportSubmission, reviewer: Employee, issue_type: IssueType
) -> None:
    """Retries do not produce duplicate work or duplicate decisions."""
    work = accept_report(reviewed_report.pk, reviewer=reviewer, **decisions(issue_type))
    retry = accept_report(
        reviewed_report.pk, reviewer=reviewer, **decisions(issue_type)
    )
    reviewed_report.refresh_from_db()
    assert retry.pk == work.pk
    assert reviewed_report.triage_state == "ACCEPTED"
    assert reviewed_report.work_item_id == work.pk
    assert work.status.code == "TRIAGED"
    assert work.issue_type.department_id == issue_type.department_id
    attempt = reviewed_report.triage_attempts.get(decision="ACCEPTED")
    assert attempt.reviewer == reviewer
    assert attempt.field_outcomes["priority"] == "HIGH"
    assert attempt.evidence["location_confirmed"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope_confirmed", False),
        ("not_duplicate_confirmed", False),
        ("location_confirmed", False),
        ("reason", " "),
        ("priority_code", "UNKNOWN"),
        ("urgency_code", "UNKNOWN"),
    ],
)
def test_acceptance_requires_explicit_complete_decisions(
    reviewed_report: ReportSubmission,
    reviewer: Employee,
    issue_type: IssueType,
    field: str,
    value: object,
) -> None:
    """No work is created when a required decision is unresolved."""
    values = decisions(issue_type)
    values[field] = value
    with pytest.raises(ValidationError):
        accept_report(reviewed_report.pk, reviewer=reviewer, **values)
    assert not WorkItem.objects.exists()


def test_acceptance_requires_reliable_location_and_authorized_reviewer(
    reviewed_report: ReportSubmission,
    reviewer: Employee,
    issue_type: IssueType,
    make_employee: Callable[..., Employee],
) -> None:
    """Reports cannot be accepted by arbitrary staff or without a pin."""
    other = make_employee("other")
    with pytest.raises(ValidationError):
        accept_report(reviewed_report.pk, reviewer=other, **decisions(issue_type))
    reviewed_report.latitude = reviewed_report.longitude = None
    reviewed_report.save(update_fields=("latitude", "longitude"))
    with pytest.raises(ValidationError):
        accept_report(reviewed_report.pk, reviewer=reviewer, **decisions(issue_type))
    assert not WorkItem.objects.exists()


def test_acceptance_rolls_back_if_audit_fails(
    reviewed_report: ReportSubmission, reviewer: Employee, issue_type: IssueType
) -> None:
    """Work and submission state roll back together when history cannot be saved."""
    with patch.object(TriageAttempt.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            accept_report(
                reviewed_report.pk, reviewer=reviewer, **decisions(issue_type)
            )
    reviewed_report.refresh_from_db()
    assert reviewed_report.triage_state == "NEEDS_REVIEW"
    assert reviewed_report.work_item_id is None
    assert not WorkItem.objects.exists()


def test_category_and_conflicting_retries_cannot_create_work(
    reviewed_report: ReportSubmission, reviewer: Employee, issue_type: IssueType
) -> None:
    """Only routable leaves may be accepted, and retries cannot change decisions."""
    category = IssueType.objects.create(
        name="Category", code="CATEGORY", kind="CATEGORY"
    )
    with pytest.raises(ValidationError):
        accept_report(reviewed_report.pk, reviewer=reviewer, **decisions(category))
    accept_report(reviewed_report.pk, reviewer=reviewer, **decisions(issue_type))
    values = decisions(issue_type)
    values["priority_code"] = "LOW"
    with pytest.raises(ValidationError):
        accept_report(reviewed_report.pk, reviewer=reviewer, **values)
    assert WorkItem.objects.count() == 1
