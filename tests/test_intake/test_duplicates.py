"""Tests for human-confirmed duplicate links."""

from collections.abc import Callable
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from employees.organisation_models import Employee
from employees.work_models import WorkItem, WorkItemStatus
from intake.models import ReportSubmission, TriageAttempt
from intake.services.duplicates import exact_location_work_candidates, link_duplicate

pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(make_employee: Callable[..., Employee]) -> Employee:
    """Create an authorized reviewer."""
    employee = make_employee()
    employee.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    return employee


@pytest.fixture
def submission() -> ReportSubmission:
    """Create a report ready for review."""
    return ReportSubmission.objects.create(
        description="A report", updates_requested=False, triage_state="NEEDS_REVIEW"
    )


def test_reviewer_links_duplicate_once(
    reviewer: Employee,
    submission: ReportSubmission,
    make_work_item: Callable[..., WorkItem],
) -> None:
    """A reviewer-confirmed link is idempotent and preserves its rationale."""
    work = make_work_item()
    for _ in range(2):
        link_duplicate(
            submission.pk, reviewer=reviewer, work_item_id=work.pk, reason="Same issue"
        )
    submission.refresh_from_db()
    assert submission.triage_state == "DUPLICATE"
    assert submission.work_item_id == work.pk
    attempt = submission.triage_attempts.get(decision="DUPLICATE")
    assert attempt.reviewer == reviewer
    assert attempt.reason == "Same issue"


def test_resolved_match_is_flagged_as_possible_recurrence(
    reviewer: Employee,
    submission: ReportSubmission,
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Reviewers can link resolved work only after confirming it is not recurrence."""
    work = make_work_item()
    work.status = WorkItemStatus.objects.get(code="RESOLVED")
    work.save(update_fields=("status",))
    with pytest.raises(ValidationError):
        link_duplicate(
            submission.pk, reviewer=reviewer, work_item_id=work.pk, reason="Same issue"
        )
    link_duplicate(
        submission.pk,
        reviewer=reviewer,
        work_item_id=work.pk,
        reason="Confirmed same incident.",
        confirmed_not_recurrence=True,
    )
    attempt = submission.triage_attempts.get(decision="DUPLICATE")
    assert attempt.evidence["possible_recurrence"] is True
    assert attempt.evidence["confirmed_not_recurrence"] is True


@pytest.mark.parametrize("status", ["CLOSED", "CANCELLED"])
def test_terminal_work_cannot_receive_duplicate_link(
    reviewer: Employee,
    submission: ReportSubmission,
    make_work_item: Callable[..., WorkItem],
    status: str,
) -> None:
    """Closed or cancelled work cannot receive new reports."""
    work = make_work_item()
    work.status = WorkItemStatus.objects.get(code=status)
    work.save(update_fields=("status",))
    with pytest.raises(ValidationError):
        link_duplicate(
            submission.pk, reviewer=reviewer, work_item_id=work.pk, reason="Same issue"
        )
    assert not submission.triage_attempts.exists()


def test_failed_audit_rolls_back_duplicate_link(
    reviewer: Employee,
    submission: ReportSubmission,
    make_work_item: Callable[..., WorkItem],
) -> None:
    """A failed audit cannot leave a linked report."""
    work = make_work_item()
    with patch.object(TriageAttempt.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            link_duplicate(
                submission.pk,
                reviewer=reviewer,
                work_item_id=work.pk,
                reason="Same issue",
            )
    submission.refresh_from_db()
    assert submission.work_item_id is None
    assert submission.triage_state == "NEEDS_REVIEW"


def test_candidate_lookup_does_not_decide_whether_reports_match(
    submission: ReportSubmission, make_work_item: Callable[..., WorkItem]
) -> None:
    """Exact-pin lookup includes resolved and closed work as context."""
    resolved = make_work_item()
    resolved.status = WorkItemStatus.objects.get(code="RESOLVED")
    resolved.save(update_fields=("status",))
    closed = make_work_item()
    closed.status = WorkItemStatus.objects.get(code="CLOSED")
    closed.save(update_fields=("status",))
    assert not exact_location_work_candidates(submission).exists()
    submission.latitude = resolved.latitude
    submission.longitude = resolved.longitude
    assert set(exact_location_work_candidates(submission)) == {resolved, closed}
